from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mixins.news import NewsMixin
from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin
from budget_terminal_app.workers import data as data_module
from budget_terminal_app.workers.data import DataWorker, NEWS_PAGE_REFRESH_REASON


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class NewsOnlyWorker(DataWorker):
    def _collect_chart_data(self, dashboard_chart_config):
        raise AssertionError('News page refresh should not collect chart data')

    def _collect_non_chart_payload(self):
        raise AssertionError('News page refresh should not collect the full dashboard payload')

    def _fetch_portfolio_news(self, ticker: str):
        return [{'category': 'portfolio', 'ticker': ticker, 'title': f'{ticker} news', '_ts': 30}]

    def _fetch_macro_news(self, ticker: str):
        if ticker == 'SPY':
            return [{'category': 'macro', 'ticker': ticker, 'title': 'Macro news', '_ts': 20}]
        return []

    def _fetch_other_news(self):
        return [{'category': 'other', 'ticker': 'OTHER', 'title': 'Other news', '_ts': 10}]

    def _filter_other_news(self, articles, existing):
        return list(articles)


class PortfolioNewsCacheWorker(DataWorker):
    def __init__(self) -> None:
        super().__init__(['AAA'], [], refresh_reason=NEWS_PAGE_REFRESH_REASON)
        self.news_fetches = 0

    def _search_portfolio_news_items(self, ticker: str):
        self.news_fetches += 1
        return [{'category': 'portfolio', 'ticker': ticker, 'title': f'{ticker} fresh news'}]


class _FakeSearchResult:
    def __init__(self, news):
        self.news = list(news)


class _FakeYFinance:
    def __init__(self) -> None:
        self.calls = []

    def Search(self, ticker, **kwargs):
        self.calls.append((ticker, kwargs))
        if ticker == 'FAIL':
            raise RuntimeError('simulated search failure')
        return _FakeSearchResult(
            [
                {
                    'title': f'{ticker} newest',
                    'publisher': 'Primary Feed',
                    'providerPublishTime': 200,
                    'link': f'https://example.test/{ticker}/newest',
                    'relatedTickers': ['BRK-B'] if ticker == 'BRK.B' else [ticker],
                },
                {
                    'title': 'Unrelated headline',
                    'publisher': 'Noise Feed',
                    'providerPublishTime': 300,
                    'link': 'https://example.test/unrelated',
                    'relatedTickers': ['OTHER'],
                },
                {
                    'title': f'{ticker} older',
                    'publisher': 'Primary Feed',
                    'providerPublishTime': 100,
                    'link': f'https://example.test/{ticker}/older',
                    'relatedTickers': [ticker.replace('.', '-')],
                },
                {
                    'title': f'{ticker} newest duplicate',
                    'publisher': 'Duplicate Feed',
                    'providerPublishTime': 150,
                    'link': f'https://example.test/{ticker}/newest',
                    'relatedTickers': [ticker.replace('.', '-')],
                },
            ]
        )


class _StackedWidget:
    def __init__(self, index: int) -> None:
        self._index = int(index)

    def currentIndex(self) -> int:
        return self._index


class RefreshRoutingHarness(WindowLifecycleMixin):
    def __init__(self, index: int) -> None:
        self.stacked_widget = _StackedWidget(index)
        self.calls = []

    def _page_label(self, index):
        return f'Page {index}'

    def refresh_data(self, **kwargs):
        self.calls.append(('dashboard', kwargs))

    def _p3_request_news_refresh(self):
        self.calls.append(('news', {}))


class NewsApplyHarness(NewsMixin):
    def __init__(self) -> None:
        self._p3_news_refresh_request_id = 7
        self._p3_news_refresh_pending = True
        self.last_data = {
            'portfolio': {'AAA': {'price': 123.0}},
            'charts': {'SPY': 'existing chart payload'},
            'chart_options': {'SPY': ['existing options payload']},
            'news': [{'category': 'portfolio', 'ticker': 'AAA', 'title': 'Old news'}],
        }
        self.updated = None
        self.statuses = []

    def update_page3(self, data):
        self.updated = data

    def _p3_set_status(self, text: str, status: str) -> None:
        self.statuses.append((text, status))


def test_worker_news_refresh_skips_dashboard_work() -> None:
    worker = NewsOnlyWorker(
        ['AAA'],
        [('SHOULD_NOT_FETCH', '1d', '1m')],
        request_id=42,
        refresh_reason=NEWS_PAGE_REFRESH_REASON,
    )
    data = worker.fetch()

    _assert(data is not None, 'News-only worker should return a payload')
    _assert(data.get('charts') == {}, 'News-only worker should not include charts')
    _assert(data.get('chart_options') == {}, 'News-only worker should not include option data')
    _assert(data.get('portfolio') == {}, 'News-only worker should not include portfolio quotes')
    _assert(data.get('targets') == [], 'News-only worker should not include target prices')
    _assert(data.get('_dashboard_refresh_meta', {}).get('refresh_reason') == NEWS_PAGE_REFRESH_REASON, 'refresh reason should be news_page_refresh')
    titles = {article.get('title') for article in data.get('news', [])}
    _assert({'AAA news', 'Macro news', 'Other news'} <= titles, 'News-only worker should collect portfolio, macro, and other news')


def test_portfolio_news_cache_does_not_poison_detail_cache() -> None:
    with DataWorker._details_cache_lock:
        DataWorker._stock_details_cache.clear()
        DataWorker._portfolio_news_cache.clear()
    worker = PortfolioNewsCacheWorker()
    try:
        first = worker._fetch_portfolio_news('AAA')
        second = worker._fetch_portfolio_news('AAA')
        _assert(first == second, 'portfolio news cache should return stable cached rows')
        _assert(worker.news_fetches == 1, 'portfolio news should use its own cache on repeat reads')
        with DataWorker._details_cache_lock:
            _assert('AAA' not in DataWorker._stock_details_cache, 'News-only fetch should not populate stock detail cache')
            _assert('AAA' in DataWorker._portfolio_news_cache, 'News-only fetch should populate portfolio news cache')
    finally:
        with DataWorker._details_cache_lock:
            DataWorker._stock_details_cache.clear()
            DataWorker._portfolio_news_cache.clear()


def test_ticker_specific_search_and_partial_failures() -> None:
    fake_yf = _FakeYFinance()
    original_yf = data_module.yf
    data_module.yf = fake_yf
    with DataWorker._details_cache_lock:
        DataWorker._portfolio_news_cache.clear()
    try:
        worker = DataWorker(['BRK.B', 'FAIL'], [], refresh_reason=NEWS_PAGE_REFRESH_REASON)
        result = worker.fetch_portfolio_news_only(max_per_ticker=3)
        articles = result['articles']
        _assert([article['title'] for article in articles] == ['BRK.B newest', 'BRK.B older'], 'portfolio search should retain only exact ticker-associated news in newest-first order')
        _assert(result['failed_tickers'] == ['FAIL'], 'one failed search should not discard successful ticker news')
        _assert(fake_yf.calls[0][0] == 'BRK.B', 'portfolio search should preserve the requested Yahoo symbol')
        _assert(fake_yf.calls[0][1]['news_count'] == 8, 'portfolio search should request the bounded candidate count')

        cached = worker.fetch_portfolio_news_only(max_per_ticker=3)
        _assert(cached['articles'] == articles, 'repeat portfolio news reads should use the stable cache')
        successful_calls = [ticker for ticker, _kwargs in fake_yf.calls if ticker == 'BRK.B']
        _assert(len(successful_calls) == 1, 'successful ticker news should be cached for repeat reads')
    finally:
        data_module.yf = original_yf
        with DataWorker._details_cache_lock:
            DataWorker._portfolio_news_cache.clear()


def test_refresh_routing_splits_news_from_dashboard() -> None:
    dashboard = RefreshRoutingHarness(0)
    dashboard._refresh_current_page()
    _assert(dashboard.calls == [('dashboard', {'force': True, 'reason': 'manual_refresh'})], 'Dashboard should still run full refresh')

    news = RefreshRoutingHarness(4)
    news._refresh_current_page()
    _assert(news.calls == [('news', {})], 'News page should run the page-local refresh path')


def test_news_refresh_preserves_existing_last_data() -> None:
    harness = NewsApplyHarness()
    harness._p3_apply_news_refresh_result(6, {'news': [{'title': 'Stale news'}]})
    _assert(harness.last_data['news'][0]['title'] == 'Old news', 'stale News refresh should be ignored')
    _assert(harness._p3_news_refresh_pending is True, 'stale News results should not clear the active refresh state')

    harness._p3_apply_news_refresh_result(
        7,
        {'news': [{'category': 'macro', 'ticker': 'SPY', 'title': 'Fresh news'}], 'charts': {}},
    )
    _assert(harness.last_data['portfolio'] == {'AAA': {'price': 123.0}}, 'portfolio data should be preserved')
    _assert(harness.last_data['charts'] == {'SPY': 'existing chart payload'}, 'chart data should be preserved')
    _assert(harness.last_data['chart_options'] == {'SPY': ['existing options payload']}, 'option data should be preserved')
    _assert(harness.last_data['news'] == [{'category': 'macro', 'ticker': 'SPY', 'title': 'Fresh news'}], 'news should be replaced')
    _assert(harness.updated == {'news': [{'category': 'macro', 'ticker': 'SPY', 'title': 'Fresh news'}]}, 'News page should render the refreshed news')
    _assert(harness.statuses[-1] == ('News refreshed: 1 article(s).', 'positive'), 'successful refresh should set status')
    _assert(harness._p3_news_refresh_pending is False, 'applied News results should clear the active refresh state')


def main() -> None:
    test_worker_news_refresh_skips_dashboard_work()
    test_portfolio_news_cache_does_not_poison_detail_cache()
    test_ticker_specific_search_and_partial_failures()
    test_refresh_routing_splits_news_from_dashboard()
    test_news_refresh_preserves_existing_last_data()
    print('News page fast refresh smoke tests passed')


if __name__ == '__main__':
    main()
