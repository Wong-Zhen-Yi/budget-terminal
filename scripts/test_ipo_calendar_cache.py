from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.workers import ipo_calendar as ipo_module
from budget_terminal_app.workers.ipo_calendar import IpoCalendarWorker


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sample_html(today: datetime.date) -> str:
    future = today + datetime.timedelta(days=14)
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
          </tbody>
        </table>
      </body>
    </html>
    """


def test_parse_filters_future_rows() -> None:
    today = datetime.date(2026, 5, 21)
    rows = IpoCalendarWorker.parse_html(_sample_html(today), today=today)
    _assert(len(rows) == 1, 'parser should keep only current/future IPO rows')
    _assert(rows[0]['symbol'] == 'TEST', 'future IPO symbol should be preserved')
    _assert(rows[0]['date'] == (today + datetime.timedelta(days=14)).isoformat(), 'date should be stored as ISO')


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


if __name__ == '__main__':
    test_parse_filters_future_rows()
    test_cache_round_trip_and_stale_fallback()
    print('IPO calendar cache smoke tests passed')
