"""US macroeconomic series for the Economic page, sourced from several public providers.

Deliberately Qt-free so the smoke tests can exercise the parsing, transform and yield-curve
rules without a ``QApplication``, matching the style of the other ``services`` modules.

Every provider here is keyless, so no new runtime dependency and no credential handling:

``treasury``
    ``home.treasury.gov`` publishes the daily par yield curve as one CSV per year, which
    carries every tenor at once. Spreads and TIPS breakevens are derived from it rather than
    fetched separately.
``bls``
    ``api.bls.gov`` answers a batched POST for up to 25 series, covering CPI, PPI and the whole
    labour block.
``nyfed``
    ``markets.newyorkfed.org`` publishes EFFR and SOFR as JSON.
``umich``
    The Surveys of Consumers publish the sentiment index as a CSV.
``fred``
    The original source, kept as the fallback for everything the direct providers do not carry
    (GDP, PCE, the Census indicators, Fed balance-sheet aggregates). FRED emits ``.`` for a
    missing observation, so its numeric coercion has to tolerate that sentinel.

FRED is reachable from most networks but not all, so the fetch treats a provider that fails
repeatedly as down and stops paying its timeout for every remaining series.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from ..dependencies import logger, pd, requests

# --------------------------------------------------------------------- endpoints

FRED_CSV_URL_TEMPLATE = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'

TREASURY_CSV_URL_TEMPLATE = (
    'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/'
    'daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv'
)
TREASURY_KIND_NOMINAL = 'daily_treasury_yield_curve'
TREASURY_KIND_REAL = 'daily_treasury_real_yield_curve'

BLS_API_URL = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'
#: Unregistered BLS callers may ask for 25 series and a ten-year span per request.
BLS_MAX_SERIES_PER_REQUEST = 25
BLS_MAX_YEARS = 10

#: The ``last/N`` form rejects anything past 500 observations, so history comes from the dated
#: search endpoint instead.
NYFED_RATE_URL_TEMPLATE = (
    'https://markets.newyorkfed.org/api/rates/{group}/{kind}/search.json'
    '?startDate={start}&endDate={end}'
)

UMICH_SENTIMENT_URL = 'https://www.sca.isr.umich.edu/files/tbmics.csv'

#: A plain client occasionally trips a bot filter on these hosts, and the same browser
#: user-agent the economic-calendar scraper uses keeps every call site consistent.
REQUEST_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0 Safari/537.36'
    ),
    'Accept': 'text/csv,application/json,text/plain,*/*',
}

REQUEST_TIMEOUT_SECONDS = 15.0
MAX_WORKERS = 6

#: A short probe timeout for the first fallback download. A reachable FRED answers in under a
#: second; a blocked one only reveals itself by timing out, and paying the full timeout once per
#: series would add minutes to every refresh on a network that cannot reach it.
FRED_PROBE_TIMEOUT_SECONDS = 6.0

#: Consecutive failures from one provider, with none of its series yet successful, that mean
#: the host is unreachable rather than a handful of series being retired. Without this the
#: fetch spends timeout x series-count (minutes) hanging whenever a provider is blocked.
PROVIDER_BLACKOUT_THRESHOLD = 4

# Backwards-compatible aliases: these names were the FRED-only spelling of the settings above.
FRED_REQUEST_HEADERS = REQUEST_HEADERS
FRED_REQUEST_TIMEOUT_SECONDS = REQUEST_TIMEOUT_SECONDS
FRED_MAX_WORKERS = MAX_WORKERS
FRED_BLACKOUT_THRESHOLD = PROVIDER_BLACKOUT_THRESHOLD

# ----------------------------------------------------------------------- caching

#: Fresh window, and the ceiling past which a cached payload is discarded rather than shown.
#: Macro series update monthly at best, so a wide stale window is correct: a failed refresh
#: should still paint last week's numbers instead of blanking the page.
ECONOMIC_PAYLOAD_CACHE_NAMESPACE = 'economic_payload'
ECONOMIC_PAYLOAD_CACHE_TTL_SECONDS = 6 * 60 * 60
ECONOMIC_STALE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

#: History retained per series in the cached payload, and how many yearly treasury CSVs the
#: curve provider pulls. Ten years keeps the charts useful while holding the serialized JSON
#: to a few hundred kilobytes.
HISTORY_YEARS = 10

# ------------------------------------------------------------------- vocabulary

GROUP_INFLATION = 'Inflation'
GROUP_LABOR = 'Labor'
GROUP_GROWTH = 'Growth'
GROUP_RATES = 'Rates'
ECONOMIC_GROUPS = (GROUP_INFLATION, GROUP_LABOR, GROUP_GROWTH, GROUP_RATES)

TRANSFORM_LEVEL = 'level'
TRANSFORM_YOY_PCT = 'yoy_pct'
TRANSFORM_MOM_PCT = 'mom_pct'
TRANSFORM_MOM_DIFF = 'mom_diff'
TRANSFORM_QOQ_SAAR = 'qoq_saar'
ECONOMIC_TRANSFORMS = (
    TRANSFORM_LEVEL,
    TRANSFORM_YOY_PCT,
    TRANSFORM_MOM_PCT,
    TRANSFORM_MOM_DIFF,
    TRANSFORM_QOQ_SAAR,
)

PROVIDER_FRED = 'fred'
PROVIDER_BLS = 'bls'
PROVIDER_TREASURY = 'treasury'
PROVIDER_TREASURY_SPREAD = 'treasury_spread'
PROVIDER_TREASURY_BREAKEVEN = 'treasury_breakeven'
PROVIDER_NYFED = 'nyfed'
PROVIDER_UMICH = 'umich'
ECONOMIC_PROVIDERS = (
    PROVIDER_FRED,
    PROVIDER_BLS,
    PROVIDER_TREASURY,
    PROVIDER_TREASURY_SPREAD,
    PROVIDER_TREASURY_BREAKEVEN,
    PROVIDER_NYFED,
    PROVIDER_UMICH,
)

PROVIDER_LABELS = {
    PROVIDER_FRED: 'FRED',
    PROVIDER_BLS: 'BLS',
    PROVIDER_TREASURY: 'US Treasury',
    PROVIDER_TREASURY_SPREAD: 'US Treasury',
    PROVIDER_TREASURY_BREAKEVEN: 'US Treasury',
    PROVIDER_NYFED: 'NY Fed',
    PROVIDER_UMICH: 'UMich',
}

#: Providers that resolve every one of their series from a single batched download. A failure
#: here takes out the whole group at once, which is what the status line reports.
BATCH_PROVIDERS = (
    PROVIDER_BLS,
    PROVIDER_TREASURY,
    PROVIDER_TREASURY_SPREAD,
    PROVIDER_TREASURY_BREAKEVEN,
    PROVIDER_NYFED,
    PROVIDER_UMICH,
)

#: Nominal days between observations, used to locate the year-ago point for a YoY transform.
_FREQUENCY_DAYS = {
    'daily': 1,
    'weekly': 7,
    'monthly': 31,
    'quarterly': 92,
    'annual': 366,
}


@dataclass(frozen=True)
class EconomicSeries:
    """One indicator: where it comes from, and how the page transforms and presents it."""

    series_id: str
    label: str
    group: str
    units: str
    frequency: str = 'monthly'
    transform: str = TRANSFORM_LEVEL
    decimals: int = 1
    higher_is_better: bool | None = None
    tenor_years: float | None = None
    note: str = ''
    provider: str = PROVIDER_FRED
    #: Provider-specific identifier: a BLS series id, a treasury CSV column, an NY Fed rate
    #: name, or ``'<minuend>|<subtrahend>'`` for a derived treasury spread or breakeven.
    provider_key: str = ''

    @property
    def source_label(self) -> str:
        """Human-readable provider plus identifier, for tooltips and the Notes column."""
        name = PROVIDER_LABELS.get(self.provider, self.provider)
        key = self.provider_key or self.series_id
        return f'{name} {key}'.strip()


#: The catalog. Ordering inside a group is the display order on that group's tab.
ECONOMIC_SERIES: tuple[EconomicSeries, ...] = (
    # ---------------------------------------------------------------- inflation
    EconomicSeries(
        'CPIAUCSL', 'CPI (YoY)', GROUP_INFLATION, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, False,
        provider=PROVIDER_BLS, provider_key='CUSR0000SA0',
    ),
    EconomicSeries(
        'CPILFESL', 'Core CPI (YoY)', GROUP_INFLATION, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, False,
        note='All items less food and energy, seasonally adjusted.',
        provider=PROVIDER_BLS, provider_key='CUSR0000SA0L1E',
    ),
    EconomicSeries(
        'PPIACO', 'Producer Prices (YoY)', GROUP_INFLATION, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, False,
        note='Final demand, seasonally adjusted.',
        provider=PROVIDER_BLS, provider_key='WPUFD4',
    ),
    EconomicSeries(
        'T5YIE', '5Y Breakeven', GROUP_INFLATION, 'percent', 'daily', TRANSFORM_LEVEL, 2, None,
        note='5Y nominal yield less the 5Y TIPS real yield.',
        provider=PROVIDER_TREASURY_BREAKEVEN, provider_key='5 Yr|5 YR',
    ),
    EconomicSeries(
        'T10YIE', '10Y Breakeven', GROUP_INFLATION, 'percent', 'daily', TRANSFORM_LEVEL, 2, None,
        note='10Y nominal yield less the 10Y TIPS real yield.',
        provider=PROVIDER_TREASURY_BREAKEVEN, provider_key='10 Yr|10 YR',
    ),
    EconomicSeries(
        'DFII10', '10Y Real Yield', GROUP_INFLATION, 'percent', 'daily', TRANSFORM_LEVEL, 2, None,
        note='10Y TIPS yield: the market real rate.',
        provider=PROVIDER_TREASURY, provider_key='real:10 YR',
    ),
    EconomicSeries('PCEPI', 'PCE Prices (YoY)', GROUP_INFLATION, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, False),
    EconomicSeries(
        'PCEPILFE', 'Core PCE (YoY)', GROUP_INFLATION, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, False,
        note='The Fed states its 2% inflation target on this series.',
    ),
    EconomicSeries('T5YIFR', '5Y5Y Forward Inflation', GROUP_INFLATION, 'percent', 'daily', TRANSFORM_LEVEL, 2, None),
    EconomicSeries('MICH', 'UMich 1Y Expectations', GROUP_INFLATION, 'percent', 'monthly', TRANSFORM_LEVEL, 1, False),
    # -------------------------------------------------------------------- labor
    EconomicSeries(
        'UNRATE', 'Unemployment Rate', GROUP_LABOR, 'percent', 'monthly', TRANSFORM_LEVEL, 1, False,
        provider=PROVIDER_BLS, provider_key='LNS14000000',
    ),
    EconomicSeries(
        'U6RATE', 'U-6 Underemployment', GROUP_LABOR, 'percent', 'monthly', TRANSFORM_LEVEL, 1, False,
        note='Includes discouraged and involuntarily part-time workers.',
        provider=PROVIDER_BLS, provider_key='LNS13327709',
    ),
    EconomicSeries(
        'PAYEMS', 'Nonfarm Payrolls (MoM)', GROUP_LABOR, 'thousands', 'monthly', TRANSFORM_MOM_DIFF, 0, True,
        provider=PROVIDER_BLS, provider_key='CES0000000001',
    ),
    EconomicSeries(
        'CIVPART', 'Participation Rate', GROUP_LABOR, 'percent', 'monthly', TRANSFORM_LEVEL, 1, True,
        provider=PROVIDER_BLS, provider_key='LNS11300000',
    ),
    EconomicSeries(
        'AHETPI', 'Avg Hourly Earnings (YoY)', GROUP_LABOR, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, None,
        note='Total private, seasonally adjusted.',
        provider=PROVIDER_BLS, provider_key='CES0500000003',
    ),
    EconomicSeries(
        'JTSJOL', 'Job Openings', GROUP_LABOR, 'thousands', 'monthly', TRANSFORM_LEVEL, 0, True,
        note='JOLTS total nonfarm openings.',
        provider=PROVIDER_BLS, provider_key='JTS000000000000000JOL',
    ),
    EconomicSeries(
        'EMRATIO', 'Employment-Population Ratio', GROUP_LABOR, 'percent', 'monthly', TRANSFORM_LEVEL, 1, True,
        provider=PROVIDER_BLS, provider_key='LNS12300000',
    ),
    EconomicSeries('ICSA', 'Initial Jobless Claims', GROUP_LABOR, 'count', 'weekly', TRANSFORM_LEVEL, 0, False),
    EconomicSeries('CCSA', 'Continuing Claims', GROUP_LABOR, 'count', 'weekly', TRANSFORM_LEVEL, 0, False),
    # ------------------------------------------------------------------- growth
    EconomicSeries(
        'UMCSENT', 'Consumer Sentiment', GROUP_GROWTH, 'index', 'monthly', TRANSFORM_LEVEL, 1, True,
        note='University of Michigan index of consumer sentiment.',
        provider=PROVIDER_UMICH, provider_key='ICS_ALL',
    ),
    EconomicSeries('GDPC1', 'Real GDP (QoQ SAAR)', GROUP_GROWTH, 'percent', 'quarterly', TRANSFORM_QOQ_SAAR, 1, True),
    EconomicSeries('INDPRO', 'Industrial Production (YoY)', GROUP_GROWTH, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, True),
    EconomicSeries('RSAFS', 'Retail Sales (YoY)', GROUP_GROWTH, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, True),
    EconomicSeries('TCU', 'Capacity Utilization', GROUP_GROWTH, 'percent', 'monthly', TRANSFORM_LEVEL, 1, True),
    EconomicSeries('DGORDER', 'Durable Goods (MoM)', GROUP_GROWTH, 'percent', 'monthly', TRANSFORM_MOM_PCT, 1, True),
    EconomicSeries('HOUST', 'Housing Starts', GROUP_GROWTH, 'thousands', 'monthly', TRANSFORM_LEVEL, 0, True),
    EconomicSeries('PERMIT', 'Building Permits', GROUP_GROWTH, 'thousands', 'monthly', TRANSFORM_LEVEL, 0, True),
    EconomicSeries('CSUSHPINSA', 'Case-Shiller Prices (YoY)', GROUP_GROWTH, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, None),
    EconomicSeries('BOPGSTB', 'Trade Balance', GROUP_GROWTH, 'millions', 'monthly', TRANSFORM_LEVEL, 0, True),
    EconomicSeries('PSAVERT', 'Personal Saving Rate', GROUP_GROWTH, 'percent', 'monthly', TRANSFORM_LEVEL, 1, None),
    # -------------------------------------------------------------------- rates
    EconomicSeries(
        'FEDFUNDS', 'Fed Funds Rate', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None,
        note='Effective federal funds rate published by the New York Fed.',
        provider=PROVIDER_NYFED, provider_key='unsecured/effr',
    ),
    EconomicSeries(
        'SOFR', 'SOFR', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None,
        note='Secured overnight financing rate.',
        provider=PROVIDER_NYFED, provider_key='secured/sofr',
    ),
    EconomicSeries(
        'DGS1MO', '1M Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 1.0 / 12.0,
        provider=PROVIDER_TREASURY, provider_key='1 Mo',
    ),
    EconomicSeries(
        'DGS3MO', '3M Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 0.25,
        provider=PROVIDER_TREASURY, provider_key='3 Mo',
    ),
    EconomicSeries(
        'DGS6MO', '6M Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 0.5,
        provider=PROVIDER_TREASURY, provider_key='6 Mo',
    ),
    EconomicSeries(
        'DGS1', '1Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 1.0,
        provider=PROVIDER_TREASURY, provider_key='1 Yr',
    ),
    EconomicSeries(
        'DGS2', '2Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 2.0,
        provider=PROVIDER_TREASURY, provider_key='2 Yr',
    ),
    EconomicSeries(
        'DGS3', '3Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 3.0,
        provider=PROVIDER_TREASURY, provider_key='3 Yr',
    ),
    EconomicSeries(
        'DGS5', '5Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 5.0,
        provider=PROVIDER_TREASURY, provider_key='5 Yr',
    ),
    EconomicSeries(
        'DGS7', '7Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 7.0,
        provider=PROVIDER_TREASURY, provider_key='7 Yr',
    ),
    EconomicSeries(
        'DGS10', '10Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 10.0,
        provider=PROVIDER_TREASURY, provider_key='10 Yr',
    ),
    EconomicSeries(
        'DGS20', '20Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 20.0,
        provider=PROVIDER_TREASURY, provider_key='20 Yr',
    ),
    EconomicSeries(
        'DGS30', '30Y Treasury', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, None, 30.0,
        provider=PROVIDER_TREASURY, provider_key='30 Yr',
    ),
    EconomicSeries(
        'T10Y2Y', '10Y-2Y Spread', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, True,
        note='Negative readings are the classic recession-warning inversion.',
        provider=PROVIDER_TREASURY_SPREAD, provider_key='10 Yr|2 Yr',
    ),
    EconomicSeries(
        'T10Y3M', '10Y-3M Spread', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, True,
        provider=PROVIDER_TREASURY_SPREAD, provider_key='10 Yr|3 Mo',
    ),
    EconomicSeries('MORTGAGE30US', '30Y Mortgage Rate', GROUP_RATES, 'percent', 'weekly', TRANSFORM_LEVEL, 2, False),
    EconomicSeries('BAMLH0A0HYM2', 'High-Yield Spread', GROUP_RATES, 'percent', 'daily', TRANSFORM_LEVEL, 2, False),
    EconomicSeries('M2SL', 'M2 Money Supply (YoY)', GROUP_RATES, 'percent', 'monthly', TRANSFORM_YOY_PCT, 1, None),
    EconomicSeries('WALCL', 'Fed Balance Sheet', GROUP_RATES, 'millions', 'weekly', TRANSFORM_LEVEL, 0, None),
)

SERIES_BY_ID = {series.series_id: series for series in ECONOMIC_SERIES}

#: Tenors used to draw the treasury curve, shortest first.
YIELD_CURVE_SERIES = tuple(series for series in ECONOMIC_SERIES if series.tenor_years is not None)

#: The headline tiles across the top of the page. Every one of these resolves from a direct
#: provider, so the strip stays populated even where FRED is unreachable.
HEADLINE_SERIES = ('CPIAUCSL', 'CPILFESL', 'UNRATE', 'PAYEMS', 'FEDFUNDS', 'DGS10', 'T10Y2Y')


# ----------------------------------------------------------------------- helpers


def _parse_iso_date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clean_points(points: Any) -> list[tuple[str, float]]:
    """Drop sentinel and unparseable rows, keeping ascending ``(iso_date, value)`` pairs."""
    cleaned: list[tuple[str, float]] = []
    for item in list(points or []):
        try:
            stamp, value = item[0], item[1]
        except (TypeError, IndexError, KeyError):
            continue
        if not _is_finite(value):
            continue
        cleaned.append((str(stamp), float(value)))
    return cleaned


def _http_get(url: str, *, timeout: float = REQUEST_TIMEOUT_SECONDS) -> Any:
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def _frame_to_points(dates: Any, values: Any) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for stamp, value in zip(dates, values):
        if stamp is None or pd.isna(stamp) or pd.isna(value):
            continue
        try:
            points.append((stamp.date().isoformat(), float(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    points.sort(key=lambda item: item[0])
    return points


def align_difference(minuend: Any, subtrahend: Any) -> list[tuple[str, float]]:
    """Subtract two dated series on their shared dates.

    Nominal and TIPS curves are published on the same schedule but not identically — a tenor
    can be missing on either side — so the difference is only defined where both have a value.
    """
    right = dict(_clean_points(subtrahend))
    result: list[tuple[str, float]] = []
    for stamp, value in _clean_points(minuend):
        other = right.get(stamp)
        if other is None:
            continue
        result.append((stamp, value - other))
    return result


# ----------------------------------------------------------------------- parsing


def parse_fred_csv(text: Any) -> list[tuple[str, float]]:
    """Parse a FRED CSV body into ascending ``(iso_date, value)`` pairs.

    FRED emits ``.`` for a missing observation and has used both ``DATE`` and
    ``observation_date`` as the first column header over time, so neither the header name nor
    the cell type can be assumed.
    """
    body = str(text or '').strip()
    if not body:
        return []
    try:
        frame = pd.read_csv(io.StringIO(body))
    except Exception as exc:
        logger.debug('FRED CSV parse failed: %s', exc)
        return []
    if frame is None or frame.empty or len(frame.columns) < 2:
        return []
    dates = pd.to_datetime(frame[frame.columns[0]], errors='coerce')
    values = pd.to_numeric(frame[frame.columns[1]], errors='coerce')
    return _frame_to_points(dates, values)


def parse_treasury_csv(text: Any) -> dict[str, list[tuple[str, float]]]:
    """Parse one yearly treasury rates CSV into ``{column_label: points}``.

    The column set changes between years — ``4 Mo`` and ``1.5 Month`` were added partway
    through — and a tenor that was not auctioned on a given day is blank, so columns are read
    by name and coerced individually rather than by position.
    """
    body = str(text or '').strip()
    if not body:
        return {}
    try:
        frame = pd.read_csv(io.StringIO(body))
    except Exception as exc:
        logger.debug('Treasury CSV parse failed: %s', exc)
        return {}
    if frame is None or frame.empty or len(frame.columns) < 2:
        return {}
    date_column = frame.columns[0]
    dates = pd.to_datetime(frame[date_column], errors='coerce', format='%m/%d/%Y')
    if dates.isna().all():
        dates = pd.to_datetime(frame[date_column], errors='coerce')
    series: dict[str, list[tuple[str, float]]] = {}
    for column in frame.columns[1:]:
        values = pd.to_numeric(frame[column], errors='coerce')
        points = _frame_to_points(dates, values)
        if points:
            series[str(column).strip()] = points
    return series


def parse_bls_payload(payload: Any) -> dict[str, list[tuple[str, float]]]:
    """Turn a BLS API response into ``{series_id: points}``.

    BLS periods are codes rather than dates: ``M01``-``M12`` are months, ``Q01``-``Q04`` are
    quarters, and ``M13``/``S03`` are annual and semiannual averages that would otherwise land
    on top of a real observation.
    """
    document = payload if isinstance(payload, dict) else {}
    results = document.get('Results') or {}
    out: dict[str, list[tuple[str, float]]] = {}
    for entry in results.get('series') or []:
        if not isinstance(entry, dict):
            continue
        series_id = str(entry.get('seriesID') or '').strip()
        if not series_id:
            continue
        points: list[tuple[str, float]] = []
        for observation in entry.get('data') or []:
            if not isinstance(observation, dict):
                continue
            stamp = _bls_period_to_date(observation.get('year'), observation.get('period'))
            if stamp is None:
                continue
            try:
                value = float(str(observation.get('value')).replace(',', ''))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            points.append((stamp, value))
        points.sort(key=lambda item: item[0])
        out[series_id] = points
    return out


def _bls_period_to_date(year: Any, period: Any) -> str | None:
    try:
        year_value = int(str(year).strip())
    except (TypeError, ValueError):
        return None
    code = str(period or '').strip().upper()
    if len(code) != 3:
        return None
    try:
        ordinal = int(code[1:])
    except ValueError:
        return None
    if code[0] == 'M':
        # M13 is the annual average, which is not an observation in the monthly series.
        if not 1 <= ordinal <= 12:
            return None
        month = ordinal
    elif code[0] == 'Q':
        if not 1 <= ordinal <= 4:
            return None
        month = ordinal * 3
    else:
        return None
    return f'{year_value:04d}-{month:02d}-01'


def parse_nyfed_rates(text: Any) -> list[tuple[str, float]]:
    """Parse an NY Fed reference-rate JSON body into ascending points."""
    try:
        document = json.loads(str(text or ''))
    except (TypeError, ValueError):
        return []
    rows = document.get('refRates') if isinstance(document, dict) else None
    points: list[tuple[str, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        stamp = _parse_iso_date(row.get('effectiveDate'))
        value = row.get('percentRate')
        if stamp is None or not _is_finite(value):
            continue
        points.append((stamp.isoformat(), float(value)))
    points.sort(key=lambda item: item[0])
    return points


_MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}


def parse_umich_csv(text: Any) -> list[tuple[str, float]]:
    """Parse the UMich sentiment CSV (``Month,YYYY,ICS_ALL``) into ascending points."""
    body = str(text or '').strip()
    if not body:
        return []
    try:
        frame = pd.read_csv(io.StringIO(body))
    except Exception as exc:
        logger.debug('UMich CSV parse failed: %s', exc)
        return []
    if frame is None or frame.empty or len(frame.columns) < 3:
        return []
    points: list[tuple[str, float]] = []
    for month_name, year, value in zip(frame.iloc[:, 0], frame.iloc[:, 1], frame.iloc[:, 2]):
        month = _MONTH_NAMES.get(str(month_name).strip().lower())
        if month is None or pd.isna(year) or pd.isna(value):
            continue
        try:
            points.append((f'{int(year):04d}-{month:02d}-01', float(value)))
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda item: item[0])
    return points


# --------------------------------------------------------------------- providers


def fetch_series_csv(series_id: Any, *, timeout: float = REQUEST_TIMEOUT_SECONDS) -> list[tuple[str, float]]:
    """Download one FRED series and return ascending ``(iso_date, value)`` pairs."""
    identifier = str(series_id or '').strip().upper()
    if not identifier:
        return []
    response = _http_get(FRED_CSV_URL_TEMPLATE.format(series_id=identifier), timeout=timeout)
    return parse_fred_csv(response.text)


def fetch_treasury_curve(*, kind: str = TREASURY_KIND_NOMINAL, years: Any = HISTORY_YEARS) -> dict[str, list[tuple[str, float]]]:
    """Download the daily par yield curve and merge the yearly files into one series per tenor.

    Treasury serves one CSV per calendar year, so a decade of history is a fan-out rather than
    a single request. A year that fails is skipped: a gap in old history is far better than
    losing the current curve.
    """
    try:
        span = max(int(years), 1)
    except (TypeError, ValueError):
        span = HISTORY_YEARS
    this_year = dt.date.today().year
    wanted = list(range(this_year - span + 1, this_year + 1))

    def _year(value: int) -> dict[str, list[tuple[str, float]]]:
        try:
            response = _http_get(TREASURY_CSV_URL_TEMPLATE.format(year=value, kind=kind))
            return parse_treasury_csv(response.text)
        except Exception as exc:
            logger.debug('Treasury %s curve for %s failed: %s', kind, value, exc)
            return {}

    merged: dict[str, list[tuple[str, float]]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for chunk in executor.map(_year, wanted):
            for column, points in chunk.items():
                merged.setdefault(column, []).extend(points)
    if not merged:
        raise RuntimeError('Treasury yield curve returned no data')
    for column, points in merged.items():
        points.sort(key=lambda item: item[0])
    return merged


def fetch_bls_batch(series_ids: Any, *, years: Any = BLS_MAX_YEARS) -> dict[str, list[tuple[str, float]]]:
    """Fetch BLS series in batches of 25, which is the unregistered per-request ceiling."""
    identifiers = [str(item).strip() for item in list(series_ids or []) if str(item).strip()]
    if not identifiers:
        return {}
    try:
        span = min(max(int(years), 1), BLS_MAX_YEARS)
    except (TypeError, ValueError):
        span = BLS_MAX_YEARS
    end_year = dt.date.today().year
    start_year = end_year - span + 1
    out: dict[str, list[tuple[str, float]]] = {}
    for offset in range(0, len(identifiers), BLS_MAX_SERIES_PER_REQUEST):
        chunk = identifiers[offset:offset + BLS_MAX_SERIES_PER_REQUEST]
        body = json.dumps({
            'seriesid': chunk,
            'startyear': str(start_year),
            'endyear': str(end_year),
        })
        headers = dict(REQUEST_HEADERS)
        headers['Content-Type'] = 'application/json'
        response = requests.post(BLS_API_URL, data=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS * 2)
        response.raise_for_status()
        payload = response.json()
        status = str((payload or {}).get('status') or '')
        if status and status != 'REQUEST_SUCCEEDED':
            # The daily quota and malformed-series errors both arrive as a 200 with a status
            # string, so the HTTP code alone cannot be trusted here.
            raise RuntimeError(f'BLS request rejected: {status}')
        out.update(parse_bls_payload(payload))
    return out


def fetch_nyfed_rate(rate_key: Any, *, years: Any = HISTORY_YEARS) -> list[tuple[str, float]]:
    """Fetch one NY Fed reference rate, given a ``'<group>/<kind>'`` key."""
    key = str(rate_key or '').strip().strip('/')
    if '/' not in key:
        return []
    group, kind = key.split('/', 1)
    try:
        span = max(int(years), 1)
    except (TypeError, ValueError):
        span = HISTORY_YEARS
    end = dt.date.today()
    start = end - dt.timedelta(days=span * 366)
    url = NYFED_RATE_URL_TEMPLATE.format(
        group=group, kind=kind, start=start.isoformat(), end=end.isoformat()
    )
    return parse_nyfed_rates(_http_get(url, timeout=REQUEST_TIMEOUT_SECONDS * 2).text)


def fetch_umich_sentiment() -> list[tuple[str, float]]:
    """Fetch the University of Michigan index of consumer sentiment."""
    return parse_umich_csv(_http_get(UMICH_SENTIMENT_URL, timeout=REQUEST_TIMEOUT_SECONDS * 2).text)


# -------------------------------------------------------------------- transforms


def latest_and_prior(points: Any) -> tuple[tuple[str, float] | None, tuple[str, float] | None]:
    """Return the last and second-to-last observations, tolerating short series."""
    items = _clean_points(points)
    if not items:
        return None, None
    if len(items) == 1:
        return items[-1], None
    return items[-1], items[-2]


def _year_ago_index(points: Sequence[tuple[str, float]], index: int, frequency: Any) -> int | None:
    """Locate the observation closest to one year before ``index``.

    Index arithmetic (``index - 12``) breaks the moment a series has a reporting gap or a
    different frequency, so the lookup runs on dates with a tolerance scaled to the series'
    own spacing.
    """
    anchor = _parse_iso_date(points[index][0])
    if anchor is None:
        return None
    target = anchor - dt.timedelta(days=365)
    # Half the nominal spacing, floored so daily series survive a holiday weekend. A tolerance
    # as wide as a whole period would happily pair a month with the month before its year-ago
    # partner whenever the series has a reporting gap.
    spacing = max(int(_FREQUENCY_DAYS.get(str(frequency or 'monthly'), 31)), 1)
    tolerance = max(spacing // 2, 5)
    best_index: int | None = None
    best_gap = tolerance + 1
    for candidate in range(index - 1, -1, -1):
        stamp = _parse_iso_date(points[candidate][0])
        if stamp is None:
            continue
        gap = abs((stamp - target).days)
        if gap < best_gap:
            best_gap = gap
            best_index = candidate
        elif stamp < target:
            # Walking further back only increases the gap once we are past the target date.
            break
    if best_index is None or best_gap > tolerance:
        return None
    return best_index


def _percent_change(current: Any, previous: Any) -> float | None:
    try:
        base = float(previous)
        value = float(current)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(base) or not math.isfinite(value) or base == 0.0:
        return None
    return (value / base - 1.0) * 100.0


def apply_transform(points: Any, transform: Any, *, frequency: Any = 'monthly') -> list[tuple[str, float]]:
    """Convert raw observations into the series the page actually displays."""
    items = _clean_points(points)
    mode = str(transform or TRANSFORM_LEVEL)
    if mode == TRANSFORM_LEVEL or not items:
        return list(items)
    result: list[tuple[str, float]] = []
    if mode == TRANSFORM_YOY_PCT:
        for index in range(len(items)):
            prior = _year_ago_index(items, index, frequency)
            if prior is None:
                continue
            change = _percent_change(items[index][1], items[prior][1])
            if change is not None:
                result.append((items[index][0], change))
        return result
    for index in range(1, len(items)):
        current = items[index][1]
        previous = items[index - 1][1]
        if mode == TRANSFORM_MOM_PCT:
            change = _percent_change(current, previous)
        elif mode == TRANSFORM_MOM_DIFF:
            change = float(current) - float(previous)
        elif mode == TRANSFORM_QOQ_SAAR:
            ratio = _percent_change(current, previous)
            change = None if ratio is None else ((1.0 + ratio / 100.0) ** 4 - 1.0) * 100.0
        else:
            change = float(current)
        if change is not None and math.isfinite(change):
            result.append((items[index][0], change))
    return result


def yoy_change(points: Any, *, frequency: Any = 'monthly') -> float | None:
    """Percent change of the latest observation against roughly one year earlier."""
    items = _clean_points(points)
    if len(items) < 2:
        return None
    prior = _year_ago_index(items, len(items) - 1, frequency)
    if prior is None:
        return None
    return _percent_change(items[-1][1], items[prior][1])


def trim_history(points: Any, years: Any = HISTORY_YEARS) -> list[list[Any]]:
    """Keep only the most recent ``years`` of observations, as JSON-friendly lists."""
    items = _clean_points(points)
    if not items:
        return []
    try:
        span = max(int(years), 1)
    except (TypeError, ValueError):
        span = HISTORY_YEARS
    newest = _parse_iso_date(items[-1][0])
    if newest is None:
        return [[stamp, value] for stamp, value in items]
    cutoff = newest - dt.timedelta(days=span * 366)
    kept: list[list[Any]] = []
    for stamp, value in items:
        parsed = _parse_iso_date(stamp)
        if parsed is None or parsed < cutoff:
            continue
        kept.append([stamp, value])
    return kept


def build_row(series: EconomicSeries, points: Any) -> dict[str, Any]:
    """Shape one series into the row dict the page and its cache both consume."""
    raw = _clean_points(points)
    transformed = apply_transform(raw, series.transform, frequency=series.frequency)
    latest, prior = latest_and_prior(transformed)
    change = None
    if latest is not None and prior is not None:
        change = float(latest[1]) - float(prior[1])
    raw_latest, _ = latest_and_prior(raw)
    return {
        'series_id': series.series_id,
        'label': series.label,
        'group': series.group,
        'units': series.units,
        'decimals': int(series.decimals),
        'frequency': series.frequency,
        'transform': series.transform,
        'higher_is_better': series.higher_is_better,
        'tenor_years': series.tenor_years,
        'note': series.note,
        'provider': series.provider,
        'source': series.source_label,
        'available': bool(latest is not None),
        'latest': None if latest is None else float(latest[1]),
        'latest_date': None if latest is None else str(latest[0]),
        'prior': None if prior is None else float(prior[1]),
        'change': change,
        'yoy': yoy_change(raw, frequency=series.frequency),
        'raw_latest': None if raw_latest is None else float(raw_latest[1]),
        'history': trim_history(transformed),
    }


def build_yield_curve(rows: Any) -> dict[str, Any]:
    """Assemble the treasury curve from whichever tenor rows came back populated."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in list(rows or []):
        if isinstance(row, dict) and row.get('series_id'):
            by_id[str(row['series_id'])] = row
    tenors: list[dict[str, Any]] = []
    for series in YIELD_CURVE_SERIES:
        row = by_id.get(series.series_id)
        if not isinstance(row, dict):
            continue
        value = row.get('latest')
        if not _is_finite(value):
            continue
        tenors.append({
            'series_id': series.series_id,
            'label': series.label.replace(' Treasury', ''),
            'years': float(series.tenor_years or 0.0),
            'yield': float(value),
            'date': row.get('latest_date'),
        })
    tenors.sort(key=lambda item: item['years'])
    lookup = {item['series_id']: item['yield'] for item in tenors}
    two_year = lookup.get('DGS2')
    ten_year = lookup.get('DGS10')
    three_month = lookup.get('DGS3MO')
    spread_10y2y = None if two_year is None or ten_year is None else ten_year - two_year
    spread_10y3m = None if three_month is None or ten_year is None else ten_year - three_month
    return {
        'tenors': tenors,
        'spread_10y2y': spread_10y2y,
        'spread_10y3m': spread_10y3m,
        'inverted_2s10s': bool(spread_10y2y is not None and spread_10y2y < 0.0),
        'inverted_3m10y': bool(spread_10y3m is not None and spread_10y3m < 0.0),
    }


# -------------------------------------------------------------------- formatting


def format_value(value: Any, units: Any, decimals: Any = 1) -> str:
    """Render one observation for a table cell, with an em dash for a missing value."""
    if not _is_finite(value):
        return '—'
    number = float(value)
    try:
        places = max(int(decimals), 0)
    except (TypeError, ValueError):
        places = 1
    kind = str(units or '').strip().lower()
    if kind == 'percent':
        return f'{number:,.{places}f}%'
    if kind == 'thousands':
        return f'{number:,.{places}f}K'
    if kind == 'millions':
        # These are reported in millions of dollars; billions read far better at this scale.
        return f'${number / 1000.0:,.1f}B'
    if kind == 'count':
        return f'{number:,.0f}'
    if kind == 'usd':
        return f'${number:,.{places}f}'
    return f'{number:,.{places}f}'


def format_change(value: Any, units: Any, decimals: Any = 1) -> str:
    """Render a period-over-period change with an explicit sign."""
    if not _is_finite(value):
        return '—'
    number = float(value)
    kind = str(units or '').strip().lower()
    if kind == 'percent':
        try:
            places = max(int(decimals), 0)
        except (TypeError, ValueError):
            places = 1
        return f'{number:+,.{places}f} pp'
    body = format_value(abs(number), units, decimals)
    return f'{"-" if number < 0 else "+"}{body}'


def describe_freshness(payload: Any) -> tuple[str, str]:
    """Return the status-bar line and severity token for a payload."""
    if not isinstance(payload, dict) or not payload.get('rows'):
        return 'No economic data loaded yet. Press Refresh to pull the latest releases.', 'muted'
    rows = [row for row in payload.get('rows') or [] if isinstance(row, dict)]
    loaded = [row for row in rows if row.get('available')]
    missing = [str(item) for item in payload.get('missing') or []]
    parts = [f'{len(loaded)} of {len(rows)} series loaded']
    generated = _parse_iso_date(payload.get('generated_at'))
    if generated is not None:
        age_days = (dt.date.today() - generated).days
        if age_days <= 0:
            parts.append('refreshed today')
        elif age_days == 1:
            parts.append('refreshed yesterday')
        else:
            parts.append(f'refreshed {age_days} days ago')
    down = [PROVIDER_LABELS.get(name, name) for name in payload.get('unreachable') or []]
    if down:
        parts.append(f'unreachable: {", ".join(sorted(set(down)))}')
        return ' · '.join(parts), 'warning'
    if missing:
        parts.append(f'{len(missing)} unavailable')
        return ' · '.join(parts), 'warning'
    return ' · '.join(parts), 'positive'


def normalize_groups(groups: Any) -> tuple[str, ...]:
    """Coerce a requested group selection to known names, defaulting to the whole catalog."""
    if groups is None:
        return tuple(ECONOMIC_GROUPS)
    if isinstance(groups, str):
        candidates: Iterable[Any] = (groups,)
    else:
        try:
            candidates = list(groups)
        except TypeError:
            return tuple(ECONOMIC_GROUPS)
    requested = {str(item).strip() for item in candidates}
    wanted = [name for name in ECONOMIC_GROUPS if name in requested]
    return tuple(wanted) if wanted else tuple(ECONOMIC_GROUPS)


# ----------------------------------------------------------------------- service


class EconomicDataService:
    """Resolve the catalog across every provider and assemble the Economic page payload."""

    def __init__(self, cache_manager: Any = None) -> None:
        self.cache_manager = cache_manager
        self._lock = threading.Lock()

    # -- cache -------------------------------------------------------------

    @staticmethod
    def _payload_cache_key(groups: Any) -> str:
        names = normalize_groups(groups)
        return 'all' if len(names) == len(ECONOMIC_GROUPS) else ':'.join(names)

    def load_cached_payload(self, groups: Any = None) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Return a cached payload plus its age, or ``None`` when it is too old to show."""
        if self.cache_manager is None:
            return None
        cached = self.cache_manager.get_json_payload(
            ECONOMIC_PAYLOAD_CACHE_NAMESPACE,
            self._payload_cache_key(groups),
            max_age_seconds=ECONOMIC_PAYLOAD_CACHE_TTL_SECONDS,
            allow_stale=True,
            return_metadata=True,
        )
        if cached is None:
            return None
        payload, metadata = cached
        age_seconds = float((metadata or {}).get('cache_age_seconds', 0.0) or 0.0)
        if not isinstance(payload, dict) or age_seconds > ECONOMIC_STALE_CACHE_TTL_SECONDS:
            return None
        return payload, {
            'cache_age_seconds': age_seconds,
            'fresh': age_seconds < ECONOMIC_PAYLOAD_CACHE_TTL_SECONDS,
        }

    def save_cached_payload(self, groups: Any, payload: Any) -> None:
        """Persist a completed payload so the next launch paints before any network call."""
        if self.cache_manager is None or not isinstance(payload, dict):
            return
        self.cache_manager.save_json_payload(
            ECONOMIC_PAYLOAD_CACHE_NAMESPACE,
            self._payload_cache_key(groups),
            payload,
        )

    def load_latest_payload(self, groups: Any = None) -> dict[str, Any] | None:
        """Return whatever is cached, for painting the page before the first fetch."""
        cached = self.load_cached_payload(groups)
        return None if cached is None else cached[0]

    # -- batch providers ---------------------------------------------------

    def _resolve_treasury(self, catalog: Sequence[EconomicSeries]) -> dict[str, list[tuple[str, float]]]:
        """Resolve every tenor, spread and breakeven from at most two curve downloads."""
        needs_real = any(
            series.provider == PROVIDER_TREASURY_BREAKEVEN
            or (series.provider == PROVIDER_TREASURY and series.provider_key.startswith('real:'))
            for series in catalog
        )
        nominal = fetch_treasury_curve(kind=TREASURY_KIND_NOMINAL)
        real: dict[str, list[tuple[str, float]]] = {}
        if needs_real:
            try:
                real = fetch_treasury_curve(kind=TREASURY_KIND_REAL)
            except Exception as exc:
                # The nominal curve is the important one; losing TIPS costs only breakevens.
                logger.debug('Treasury real yield curve unavailable: %s', exc)
        resolved: dict[str, list[tuple[str, float]]] = {}
        for series in catalog:
            key = series.provider_key
            if series.provider == PROVIDER_TREASURY:
                if key.startswith('real:'):
                    resolved[series.series_id] = list(real.get(key[5:].strip(), []))
                else:
                    resolved[series.series_id] = list(nominal.get(key, []))
            elif series.provider == PROVIDER_TREASURY_SPREAD and '|' in key:
                left, right = (part.strip() for part in key.split('|', 1))
                resolved[series.series_id] = align_difference(nominal.get(left), nominal.get(right))
            elif series.provider == PROVIDER_TREASURY_BREAKEVEN and '|' in key:
                left, right = (part.strip() for part in key.split('|', 1))
                resolved[series.series_id] = align_difference(nominal.get(left), real.get(right))
        return resolved

    def _resolve_bls(self, catalog: Sequence[EconomicSeries]) -> dict[str, list[tuple[str, float]]]:
        by_key = {series.provider_key: series.series_id for series in catalog if series.provider_key}
        fetched = fetch_bls_batch(list(by_key))
        return {series_id: list(fetched.get(key, [])) for key, series_id in by_key.items()}

    @staticmethod
    def _resolve_nyfed(catalog: Sequence[EconomicSeries]) -> dict[str, list[tuple[str, float]]]:
        resolved: dict[str, list[tuple[str, float]]] = {}
        for series in catalog:
            resolved[series.series_id] = fetch_nyfed_rate(series.provider_key)
        return resolved

    @staticmethod
    def _resolve_umich(catalog: Sequence[EconomicSeries]) -> dict[str, list[tuple[str, float]]]:
        points = fetch_umich_sentiment()
        return {series.series_id: list(points) for series in catalog}

    def _batch_resolvers(self) -> dict[str, Callable[[Sequence[EconomicSeries]], dict[str, list[tuple[str, float]]]]]:
        # The three treasury providers share one resolver because they all come out of the same
        # pair of curve downloads; grouping them here stops the curve being fetched three times.
        return {
            PROVIDER_TREASURY: self._resolve_treasury,
            PROVIDER_BLS: self._resolve_bls,
            PROVIDER_NYFED: self._resolve_nyfed,
            PROVIDER_UMICH: self._resolve_umich,
        }

    @staticmethod
    def _resolver_group(provider: str) -> str:
        if provider in (PROVIDER_TREASURY_SPREAD, PROVIDER_TREASURY_BREAKEVEN):
            return PROVIDER_TREASURY
        return provider

    # -- fetch -------------------------------------------------------------

    def fetch(
        self,
        *,
        groups: Any = None,
        force: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
        fetcher: Callable[[str], list[tuple[str, float]]] | None = None,
    ) -> dict[str, Any]:
        """Resolve every series in the requested groups and build the payload.

        Batched providers run first and in parallel, then anything still empty falls back to
        one FRED download per series. A failure never raises: the series lands in ``missing``
        and the page renders the rest, because one unreachable host must not blank the page.
        """
        if not force:
            cached = self.load_cached_payload(groups)
            if cached is not None and cached[1].get('fresh'):
                return cached[0]
        wanted = normalize_groups(groups)
        catalog = [series for series in ECONOMIC_SERIES if series.group in wanted]
        cancelled = (lambda: bool(cancel())) if cancel is not None else (lambda: False)

        resolved: dict[str, list[tuple[str, float]]] = {}
        unreachable: list[str] = []
        completed = 0
        # `fetcher` overrides every provider so tests (and any caller that already has the data)
        # can drive the whole catalog through one function.
        batches = {} if fetcher is not None else self._plan_batches(catalog)
        total = len(batches) + (len(catalog) if fetcher is not None else self._fallback_count(catalog))

        def _report(label: str) -> None:
            nonlocal completed
            completed += 1
            if progress is not None:
                try:
                    progress(completed, max(total, 1), label)
                except Exception:
                    pass

        if batches:
            resolvers = self._batch_resolvers()
            with ThreadPoolExecutor(max_workers=min(len(batches), MAX_WORKERS)) as executor:
                futures = {
                    name: executor.submit(resolvers[name], members)
                    for name, members in batches.items()
                    if not cancelled()
                }
                for name, future in futures.items():
                    label = PROVIDER_LABELS.get(name, name)
                    try:
                        resolved.update(future.result())
                    except Exception as exc:
                        logger.warning('Economic provider %s failed: %s', label, exc)
                        unreachable.append(name)
                    _report(label)

        fallback = [
            series for series in catalog
            if not resolved.get(series.series_id) and (fetcher is not None or series.provider == PROVIDER_FRED)
        ]
        if fallback:
            resolved.update(self._fetch_fallback(fallback, fetcher, cancelled, _report, unreachable))

        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for series in catalog:
            points = resolved.get(series.series_id) or []
            if not points:
                missing.append(series.series_id)
            rows.append(build_row(series, points))

        order = {series.series_id: index for index, series in enumerate(ECONOMIC_SERIES)}
        rows.sort(key=lambda row: order.get(str(row.get('series_id')), 10_000))
        loaded = [row for row in rows if row.get('available')]
        payload = {
            'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
            'source': 'US Treasury, BLS, NY Fed, UMich and FRED',
            'groups': list(wanted),
            'rows': rows,
            'missing': missing,
            'unreachable': sorted(set(unreachable)),
            'yield_curve': build_yield_curve(rows),
        }
        if not loaded:
            # A total blackout must never overwrite a good cached payload with an empty one.
            previous = self.load_latest_payload(groups)
            if isinstance(previous, dict) and any(
                row.get('available') for row in previous.get('rows') or [] if isinstance(row, dict)
            ):
                return previous
        with self._lock:
            self.save_cached_payload(groups, payload)
        return payload

    @staticmethod
    def _plan_batches(catalog: Sequence[EconomicSeries]) -> dict[str, list[EconomicSeries]]:
        batches: dict[str, list[EconomicSeries]] = {}
        for series in catalog:
            if series.provider == PROVIDER_FRED:
                continue
            batches.setdefault(EconomicDataService._resolver_group(series.provider), []).append(series)
        return batches

    @staticmethod
    def _fallback_count(catalog: Sequence[EconomicSeries]) -> int:
        return sum(1 for series in catalog if series.provider == PROVIDER_FRED)

    @staticmethod
    def _fetch_fallback(
        fallback: Sequence[EconomicSeries],
        fetcher: Callable[[str], list[tuple[str, float]]] | None,
        cancelled: Callable[[], bool],
        report: Callable[[str], None],
        unreachable: list[str],
    ) -> dict[str, list[tuple[str, float]]]:
        """Download the per-series fallback provider, giving up once it looks unreachable."""
        download = fetcher or fetch_series_csv
        pending = list(fallback)
        state = {'failures': 0, 'successes': 0, 'blackout': False}
        resolved: dict[str, list[tuple[str, float]]] = {}

        def _one(series: EconomicSeries, *, timeout: float | None = None) -> list[tuple[str, float]]:
            if state['blackout'] or cancelled():
                return []
            try:
                if timeout is not None and fetcher is None:
                    return download(series.series_id, timeout=timeout)
                return download(series.series_id)
            except Exception as exc:
                logger.debug('Fallback fetch for %s failed: %s', series.series_id, exc)
                return []

        # Probe with the first series before fanning out. One short timeout is the whole cost
        # of a blocked FRED, instead of one full timeout for every remaining series.
        probe = pending.pop(0)
        points = _one(probe, timeout=FRED_PROBE_TIMEOUT_SECONDS)
        resolved[probe.series_id] = points
        report(probe.label)
        if points:
            state['successes'] += 1
        elif fetcher is None:
            logger.warning('FRED did not answer the reachability probe; skipping its series.')
            state['blackout'] = True

        def _batch(series: EconomicSeries) -> tuple[EconomicSeries, list[tuple[str, float]]]:
            found = _one(series)
            if found:
                state['successes'] += 1
                state['failures'] = 0
            else:
                state['failures'] += 1
                if state['successes'] == 0 and state['failures'] >= PROVIDER_BLACKOUT_THRESHOLD:
                    logger.warning('FRED appears unreachable; abandoning the remaining series.')
                    state['blackout'] = True
            return series, found

        if pending:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for series, found in executor.map(_batch, pending):
                    resolved[series.series_id] = found
                    report(series.label)
        if state['blackout'] and fetcher is None:
            unreachable.append(PROVIDER_FRED)
        return resolved
