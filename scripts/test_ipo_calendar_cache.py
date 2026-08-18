from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.workers import ipo_calendar as ipo_module
from budget_terminal_app.workers.ipo_calendar import CompletedIpoWorker, IpoCalendarWorker


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sample_html(today: datetime.date) -> str:
    future = today + datetime.timedelta(days=14)
    year_end = datetime.date(today.year, 12, 15)
    next_year = datetime.date(today.year + 1, 1, 7)
    past = today - datetime.timedelta(days=7)
    return f"""
    <html>
      <body>
        <table>
          <thead>
            <tr>
              <th>IPO Date</th>
              <th>Symbol</th>
              <th>Company Name</th>
              <th>Exchange</th>
              <th>Price Range</th>
              <th>Shares Offered</th>
              <th>Deal Size</th>
              <th>Market Cap</th>
              <th>Revenue</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{future.strftime('%b %d, %Y')}</td>
              <td>TEST</td>
              <td>Test IPO Inc.</td>
              <td>NASDAQ</td>
              <td>$10.00 - $12.00</td>
              <td>5,000,000</td>
              <td>55.00M</td>
              <td>120.00M</td>
              <td>10.00M</td>
            </tr>
            <tr>
              <td>{past.strftime('%b %d, %Y')}</td>
              <td>OLD</td>
              <td>Old IPO Corp.</td>
              <td>NYSE</td>
              <td>$8.00</td>
              <td>1,000,000</td>
              <td>8.00M</td>
              <td>50.00M</td>
              <td>-</td>
            </tr>
            <tr>
              <td>{year_end.strftime('%b %d, %Y')}</td>
              <td>REST</td>
              <td>Rest Of Year IPO Corp.</td>
              <td>NYSE</td>
              <td>$20.00</td>
              <td>2,000,000</td>
              <td>40.00M</td>
              <td>150.00M</td>
              <td>25.00M</td>
            </tr>
            <tr>
              <td>{next_year.strftime('%b %d, %Y')}</td>
              <td>NEXT</td>
              <td>Next Year IPO Corp.</td>
              <td>NASDAQ</td>
              <td>$12.00</td>
              <td>1,000,000</td>
              <td>12.00M</td>
              <td>60.00M</td>
              <td>5.00M</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """


def _sample_upcoming_yfinance_frame(today: datetime.date) -> pd.DataFrame:
    near = today + datetime.timedelta(days=3)
    year_end = datetime.date(today.year, 12, 15)
    next_year = datetime.date(today.year + 1, 1, 7)
    past = today - datetime.timedelta(days=3)
    return pd.DataFrame(
        [
            {
                'Company': 'Near Term IPO Inc.',
                'Exchange': 'Nasdaq',
                'Date': pd.Timestamp(near),
                'Price From': pd.NA,
                'Price To': pd.NA,
                'Price': 10.0,
                'Shares': 1_000_000,
            },
            {
                'Company': 'Rest Of Year IPO Corp.',
                'Exchange': 'NYSE',
                'Date': pd.Timestamp(year_end),
                'Price From': 20.0,
                'Price To': 22.0,
                'Price': pd.NA,
                'Shares': 2_000_000,
            },
            {
                'Company': 'Past IPO Corp.',
                'Exchange': 'Nasdaq',
                'Date': pd.Timestamp(past),
                'Price From': pd.NA,
                'Price To': pd.NA,
                'Price': 8.0,
                'Shares': 1_000_000,
            },
            {
                'Company': 'Next Year IPO Corp.',
                'Exchange': 'NYSE',
                'Date': pd.Timestamp(next_year),
                'Price From': pd.NA,
                'Price To': pd.NA,
                'Price': 12.0,
                'Shares': 1_000_000,
            },
        ],
        index=pd.Index(['NEAR', 'REST', 'PAST', 'NEXT'], name='Symbol'),
    )


def _sample_completed_html(today: datetime.date) -> str:
    recent = today - datetime.timedelta(days=5)
    january = datetime.date(today.year, 1, 6)
    future = today + datetime.timedelta(days=14)
    previous_year = datetime.date(today.year - 1, 12, 20)
    return f"""
    <html>
      <body>
        <table>
          <thead>
            <tr>
              <th>IPO Date</th>
              <th>Symbol</th>
              <th>Company Name</th>
              <th>IPO Price</th>
              <th>Current</th>
              <th>Return</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{recent.strftime('%b %d, %Y')}</td>
              <td>DONE</td>
              <td>Done IPO Inc.</td>
              <td>$10.00</td>
              <td>$12.50</td>
              <td>25.00%</td>
            </tr>
            <tr>
              <td>{january.strftime('%b %d, %Y')}</td>
              <td>JANU</td>
              <td>January IPO Corp.</td>
              <td>$8.00</td>
              <td>$7.20</td>
              <td>-10.00%</td>
            </tr>
            <tr>
              <td>{future.strftime('%b %d, %Y')}</td>
              <td>FUTR</td>
              <td>Future IPO Ltd.</td>
              <td>$15.00</td>
              <td>$15.00</td>
              <td>-</td>
            </tr>
            <tr>
              <td>{previous_year.strftime('%b %d, %Y')}</td>
              <td>PREV</td>
              <td>Previous IPO Corp.</td>
              <td>$11.00</td>
              <td>$13.00</td>
              <td>18.18%</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """


def _sample_completed_yfinance_frame(today: datetime.date) -> pd.DataFrame:
    recent = today - datetime.timedelta(days=5)
    january = datetime.date(today.year, 1, 6)
    future = today + datetime.timedelta(days=14)
    previous_year = datetime.date(today.year - 1, 12, 20)
    return pd.DataFrame(
        [
            {'Company': 'Done IPO Inc.', 'Exchange': 'Nasdaq', 'Date': pd.Timestamp(recent), 'Price From': 10.0, 'Price To': 10.0, 'Price': pd.NA, 'Shares': 1_000_000},
            {'Company': 'January IPO Corp.', 'Exchange': 'NYSE', 'Date': pd.Timestamp(january), 'Price From': pd.NA, 'Price To': pd.NA, 'Price': 8.0, 'Shares': 2_000_000},
            {'Company': 'Future IPO Ltd.', 'Exchange': 'Nasdaq', 'Date': pd.Timestamp(future), 'Price From': pd.NA, 'Price To': pd.NA, 'Price': 15.0, 'Shares': 1_000_000},
            {'Company': 'Previous IPO Corp.', 'Exchange': 'NYSE', 'Date': pd.Timestamp(previous_year), 'Price From': pd.NA, 'Price To': pd.NA, 'Price': 11.0, 'Shares': 1_000_000},
        ],
        index=pd.Index(['DONE', 'JANU', 'FUTR', 'PREV'], name='Symbol'),
    )


def test_parse_filters_future_rows() -> None:
    today = datetime.date(2026, 5, 21)
    rows = IpoCalendarWorker.parse_html(_sample_html(today), today=today)
    _assert(len(rows) == 2, 'parser should keep future IPO rows through year-end')
    _assert(rows[0]['symbol'] == 'TEST', 'future IPO symbol should be preserved')
    _assert(rows[0]['date'] == (today + datetime.timedelta(days=14)).isoformat(), 'date should be stored as ISO')
    _assert(rows[1]['symbol'] == 'REST', 'rest-of-year IPO symbol should be preserved')
    _assert(rows[1]['date'] == datetime.date(today.year, 12, 15).isoformat(), 'year-end date should be stored as ISO')


def test_parse_yfinance_filters_rest_of_year_rows() -> None:
    today = datetime.date(2026, 5, 21)
    rows = IpoCalendarWorker.parse_yfinance_frame(
        _sample_upcoming_yfinance_frame(today),
        start_date=today,
        end_date=datetime.date(today.year, 12, 31),
        completed=False,
    )
    _assert(len(rows) == 2, 'yfinance parser should keep upcoming IPO rows through year-end')
    symbols = [row['symbol'] for row in rows]
    _assert(symbols == ['NEAR', 'REST'], 'yfinance parser should exclude past and next-year rows')
    _assert(rows[0]['price_range'] == '$10.00', 'single yfinance price should be formatted')
    _assert(rows[0]['shares_offered'] == '1,000,000', 'yfinance shares should be formatted')
    _assert(rows[1]['price_range'] == '$20.00 - $22.00', 'yfinance price range should be formatted')


def test_parse_completed_filters_current_year_rows() -> None:
    today = datetime.date(2026, 5, 21)
    rows = CompletedIpoWorker.parse_html(_sample_completed_html(today), today=today, year=today.year)
    _assert(len(rows) == 2, 'completed parser should keep current-year IPOs through today')
    symbols = [row['symbol'] for row in rows]
    _assert(symbols == ['DONE', 'JANU'], 'completed rows should sort newest first')
    _assert(rows[0]['ipo_price'] == '$10.00', 'IPO price should be preserved')
    _assert(rows[0]['current_price'] == '$12.50', 'current price should be preserved')
    _assert(rows[0]['return'] == '25.00%', 'return should be preserved')


def test_parse_completed_yfinance_rows() -> None:
    today = datetime.date(2026, 5, 21)
    rows = IpoCalendarWorker.parse_yfinance_frame(
        _sample_completed_yfinance_frame(today),
        start_date=datetime.date(today.year, 1, 1),
        end_date=today,
        completed=True,
    )
    _assert(len(rows) == 2, 'completed yfinance parser should keep current-year IPOs through today')
    symbols = [row['symbol'] for row in rows]
    _assert(symbols == ['DONE', 'JANU'], 'completed yfinance rows should sort newest first')
    _assert(rows[0]['ipo_price'] == '$10.00', 'completed yfinance IPO price should be formatted')
    _assert(rows[0]['current_price'] == '--', 'completed yfinance should leave current price unavailable')
    _assert(rows[0]['return'] == '--', 'completed yfinance should leave return unavailable')


def test_cache_round_trip_and_stale_fallback() -> None:
    original_cache_path = ipo_module.ipo_calendar_cache_path
    original_fetch_live_payload = IpoCalendarWorker.fetch_live_payload
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / 'upcoming_us.json'
        ipo_module.ipo_calendar_cache_path = lambda: cache_path
        try:
            today = datetime.date.today()
            rows = IpoCalendarWorker.parse_html(_sample_html(today), today=today)
            IpoCalendarWorker.save_cached_payload({
                'rows': rows,
                'source': 'Unit Test',
                'source_url': 'https://example.test/ipos',
                'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
            })
            cached = IpoCalendarWorker.load_cached_payload(allow_stale=True)
            _assert(cached is not None, 'saved IPO cache should load')
            _assert(cached['rows'][0]['symbol'] == 'TEST', 'cached IPO row should round trip')

            def _raise_fetch(cls):
                raise RuntimeError('synthetic fetch failure')

            IpoCalendarWorker.fetch_live_payload = classmethod(_raise_fetch)
            fallback = IpoCalendarWorker.fetch(force=True)
            _assert(fallback.get('stale') is True, 'failed force refresh should fall back to stale cache')
            _assert(fallback['rows'][0]['symbol'] == 'TEST', 'stale fallback should preserve cached rows')
        finally:
            ipo_module.ipo_calendar_cache_path = original_cache_path
            IpoCalendarWorker.fetch_live_payload = original_fetch_live_payload


def test_completed_cache_round_trip_and_stale_fallback() -> None:
    original_cache_path = ipo_module.completed_ipo_cache_path
    original_fetch_live_payload = CompletedIpoWorker.fetch_live_payload
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / 'completed_us_2026.json'
        ipo_module.completed_ipo_cache_path = lambda year=None: cache_path
        try:
            today = datetime.date(2026, 5, 21)
            rows = CompletedIpoWorker.parse_html(_sample_completed_html(today), today=today, year=today.year)
            CompletedIpoWorker.save_cached_payload({
                'rows': rows,
                'source': 'Unit Test Completed',
                'source_url': 'https://example.test/ipos/2026',
                'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
                'year': today.year,
            }, year=today.year)
            cached = CompletedIpoWorker.load_cached_payload(year=today.year, allow_stale=True)
            _assert(cached is not None, 'saved completed IPO cache should load')
            _assert(cached['rows'][0]['symbol'] == 'DONE', 'completed IPO row should round trip')

            def _raise_fetch(cls, *, year=None):
                raise RuntimeError('synthetic completed fetch failure')

            CompletedIpoWorker.fetch_live_payload = classmethod(_raise_fetch)
            fallback = CompletedIpoWorker.fetch(force=True, year=today.year)
            _assert(fallback.get('stale') is True, 'failed completed force refresh should fall back to stale cache')
            _assert(fallback['rows'][0]['symbol'] == 'DONE', 'completed stale fallback should preserve cached rows')
        finally:
            ipo_module.completed_ipo_cache_path = original_cache_path
            CompletedIpoWorker.fetch_live_payload = original_fetch_live_payload


if __name__ == '__main__':
    test_parse_filters_future_rows()
    test_parse_yfinance_filters_rest_of_year_rows()
    test_parse_completed_filters_current_year_rows()
    test_parse_completed_yfinance_rows()
    test_cache_round_trip_and_stale_fallback()
    test_completed_cache_round_trip_and_stale_fallback()
    print('IPO calendar cache smoke tests passed')
