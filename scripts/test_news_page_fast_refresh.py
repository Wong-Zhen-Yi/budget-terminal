from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin
from budget_terminal_app.workers import data as data_module
from budget_terminal_app.workers import news_sources
from budget_terminal_app.workers.data import DataWorker, NEWS_PAGE_REFRESH_REASON


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class NewsOnlyWorker(DataWorker):
    def _collect_chart_data(self, dashboard_chart_config):
        raise AssertionError('News page refresh should not collect chart data')

    def _collect_non_chart_payload(self):
        raise AssertionError('News page refresh should not collect the full dashboard payload')

    def _fetch_portfolio_news_with_status(self, ticker: str):
        return ([{'category': 'portfolio', 'ticker': ticker, 'title': f'{ticker} news', '_ts': 30}], None)

    def _fetch_macro_news(self, ticker: str):
        if ticker == 'SPY':
            return [{'category': 'macro', 'ticker': ticker, 'title': 'Macro news', '_ts': 20}]
        return []

    def _fetch_other_news_with_status(self):
        return {
            'articles': [{'category': 'other', 'ticker': 'OTHER', 'title': 'Other news', '_ts': 10}],
            'fresh_sources': ['Test Feed'],
            'stale_sources': [],
            'failed_sources': [],
            'cache_hit': False,
        }

    def _filter_other_news(self, articles, existing):
        return list(articles)


class PortfolioNewsCacheWorker(DataWorker):
    def __init__(self) -> None:
        super().__init__(['AAA'], [], refresh_reason=NEWS_PAGE_REFRESH_REASON)
        self.news_fetches = 0

    def _search_portfolio_news_items(self, ticker: str):
        self.news_fetches += 1
        return [{'category': 'portfolio', 'ticker': ticker, 'title': f'{ticker} fresh news'}]


class ConcurrentNewsWorker(DataWorker):
    def __init__(self) -> None:
        super().__init__(['AAA'], [], refresh_reason=NEWS_PAGE_REFRESH_REASON)
        self.barrier = threading.Barrier(3)

    def _wait_for_other_branches(self) -> None:
        self.barrier.wait(timeout=1.0)
        time.sleep(0.05)

    def _collect_portfolio_news_page(self):
        self._wait_for_other_branches()
        return ([{'category': 'portfolio', 'ticker': 'AAA', 'title': 'Portfolio'}], [])

    def _collect_macro_news_page(self):
        self._wait_for_other_branches()
        return [{'category': 'macro', 'ticker': 'SPY', 'title': 'Macro'}]

    def _fetch_other_news_with_status(self):
        self._wait_for_other_branches()
        return {
            'articles': [{'category': 'other', 'ticker': 'OTHER', 'title': 'Other'}],
            'fresh_sources': ['Test Feed'],
            'stale_sources': [],
            'failed_sources': [],
            'cache_hit': False,
        }


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
        if ticker == 'EMPTY':
            return _FakeSearchResult([])
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

    def _p34_request_news_refresh(self):
        self.calls.append(('news', {}))


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


def test_ad_hoc_ticker_news_contract_and_cancellation() -> None:
    fake_yf = _FakeYFinance()
    original_yf = data_module.yf
    data_module.yf = fake_yf
    with DataWorker._details_cache_lock:
        DataWorker._portfolio_news_cache.clear()
    try:
        worker = DataWorker(['brk.b', 'EMPTY', 'FAIL', 'BRK.B'], [])
        result = worker.fetch_ticker_news_only(max_per_ticker=1)
        _assert(result['queried_tickers'] == ['BRK.B', 'EMPTY', 'FAIL'], 'ad hoc search should normalize and deduplicate tickers')
        _assert([article['title'] for article in result['articles']] == ['BRK.B newest'], 'ad hoc search should enforce the per-ticker newest-first limit')
        _assert(all(article['category'] == 'search' for article in result['articles']), 'ad hoc rows should use the search category')
        _assert(result['empty_tickers'] == ['EMPTY'], 'successful zero-result searches should remain distinct from failures')
        _assert(result['failed_tickers'] == ['FAIL'], 'failed ad hoc searches should preserve partial results')

        cached = worker.fetch_ticker_news_only(max_per_ticker=1)
        _assert(cached['articles'] == result['articles'], 'repeat ad hoc searches should reuse cached ticker news')
        successful_calls = [ticker for ticker, _kwargs in fake_yf.calls if ticker == 'BRK.B']
        _assert(len(successful_calls) == 1, 'ad hoc search should share the existing 15-minute ticker cache')

        calls_before_cancel = len(fake_yf.calls)
        cancelled = DataWorker(['AAPL'], [], cancel_check=lambda: True).fetch_ticker_news_only()
        _assert(cancelled['queried_tickers'] == ['AAPL'] and cancelled['articles'] == [], 'pre-cancelled ad hoc search should return an empty contract')
        _assert(len(fake_yf.calls) == calls_before_cancel, 'pre-cancelled ad hoc search should not call Yahoo')
    finally:
        data_module.yf = original_yf
        with DataWorker._details_cache_lock:
            DataWorker._portfolio_news_cache.clear()


def _test_feed(name: str) -> news_sources.NewsFeed:
    return news_sources.NewsFeed(name, f'https://example.test/{name.lower()}')


def _test_feed_article(feed: news_sources.NewsFeed, *, url: str | None = None) -> dict:
    return {
        'category': 'other',
        'ticker': 'OTHER',
        'title': f'{feed.source} headline',
        'source': feed.source,
        'url': url or f'{feed.url}/article',
        '_ts': 100,
        '_trader_score': 1,
    }


def test_general_news_sources_run_concurrently_and_dedupe() -> None:
    feeds = tuple(_test_feed(name) for name in ('One', 'Two', 'Three'))
    barrier = threading.Barrier(len(feeds))
    original_fetch = news_sources._fetch_feed_articles
    news_sources._clear_news_feed_cache()

    def delayed_fetch(feed, _ticker_universe):
        barrier.wait(timeout=1.0)
        time.sleep(0.05)
        return [_test_feed_article(feed, url='https://example.test/shared')]

    news_sources._fetch_feed_articles = delayed_fetch
    try:
        started = time.perf_counter()
        result = news_sources._fetch_ranked_news_with_status(
            feeds,
            [],
            limit=10,
            candidate_limit=10,
            log_label='Test feed',
        )
        elapsed = time.perf_counter() - started
        _assert(elapsed < 0.25, f'feed fan-out should complete concurrently, took {elapsed:.3f}s')
        _assert(len(result['articles']) == 1, 'cross-source article URLs should remain deduplicated')
        _assert(result['fresh_sources'] == ['One', 'Two', 'Three'], 'all completed sources should be marked fresh')
        _assert(result['failed_sources'] == [], 'successful sources should not be marked failed')
    finally:
        news_sources._fetch_feed_articles = original_fetch
        news_sources._clear_news_feed_cache()


def test_general_news_stale_fallback_and_unavailable_source() -> None:
    feeds = (_test_feed('One'), _test_feed('Two'))
    original_fetch = news_sources._fetch_feed_articles
    news_sources._clear_news_feed_cache()
    try:
        news_sources._fetch_feed_articles = lambda feed, _tickers: [_test_feed_article(feed)]
        fresh = news_sources._fetch_ranked_news_with_status(
            feeds,
            [],
            limit=10,
            candidate_limit=10,
            log_label='Test feed',
        )
        _assert(len(fresh['articles']) == 2, 'successful feed rows should populate the stale fallback cache')

        def fail_fetch(_feed, _tickers):
            raise TimeoutError('simulated timeout')

        news_sources._fetch_feed_articles = fail_fetch
        stale = news_sources._fetch_ranked_news_with_status(
            feeds,
            [],
            limit=10,
            candidate_limit=10,
            log_label='Test feed',
        )
        _assert(len(stale['articles']) == 2, 'failed sources should reuse their prior successful rows')
        _assert(stale['stale_sources'] == ['One', 'Two'], 'fallback sources should be explicitly marked stale')
        _assert(stale['failed_sources'] == ['One', 'Two'], 'underlying source failures should remain visible')

        with news_sources._NEWS_FEED_CACHE_LOCK:
            for feed in feeds:
                _timestamp, rows = news_sources._NEWS_FEED_CACHE[feed.url]
                news_sources._NEWS_FEED_CACHE[feed.url] = (
                    time.time() - news_sources.NEWS_FEED_STALE_FALLBACK_SECONDS - 1,
                    rows,
                )
        unavailable = news_sources._fetch_ranked_news_with_status(
            feeds,
            [],
            limit=10,
            candidate_limit=10,
            log_label='Test feed',
        )
        _assert(unavailable['articles'] == [], 'a failed source with an expired fallback should be omitted')
        _assert(unavailable['stale_sources'] == [], 'expired fallback must not be labeled stale')
        _assert(unavailable['failed_sources'] == ['One', 'Two'], 'unavailable sources should be reported')
    finally:
        news_sources._fetch_feed_articles = original_fetch
        news_sources._clear_news_feed_cache()


def test_general_news_timeout_and_cancellation_contract() -> None:
    feed = _test_feed('Timeout')
    original_get = news_sources.requests.get
    observed = {}

    def fail_get(_url, **kwargs):
        observed['timeout'] = kwargs.get('timeout')
        raise TimeoutError('simulated request timeout')

    news_sources.requests.get = fail_get
    try:
        try:
            news_sources._fetch_feed_articles(feed, set())
        except TimeoutError:
            pass
        else:
            raise AssertionError('simulated source timeout should propagate to the source collector')
        _assert(observed.get('timeout') == 4, 'each RSS request should use the four-second deadline')
    finally:
        news_sources.requests.get = original_get

    calls = []
    original_fetch = news_sources._fetch_feed_articles
    news_sources._fetch_feed_articles = lambda *_args: calls.append(True) or []
    try:
        cancelled = news_sources._fetch_ranked_news_with_status(
            (feed,),
            [],
            limit=10,
            candidate_limit=10,
            cancel_check=lambda: True,
            log_label='Test feed',
        )
        _assert(cancelled['cancelled'] is True, 'cancelled fetches should be labeled')
        _assert(cancelled['articles'] == [], 'cancelled fetches should discard articles')
        _assert(calls == [], 'pre-cancelled fetches should not start source requests')
    finally:
        news_sources._fetch_feed_articles = original_fetch


def test_news_page_branches_run_concurrently() -> None:
    worker = ConcurrentNewsWorker()
    started = time.perf_counter()
    payload = worker._collect_news_page_payload()
    elapsed = time.perf_counter() - started
    _assert(payload is not None, 'concurrent News page collection should return a payload')
    _assert(elapsed < 0.25, f'News page branches should overlap, took {elapsed:.3f}s')
    titles = {article.get('title') for article in payload['news']}
    _assert(titles == {'Portfolio', 'Macro', 'Other'}, 'all concurrent branches should contribute rows')
    _assert(payload['_news_refresh_meta']['fresh_sources'] == ['Test Feed'], 'source status should flow into refresh metadata')


def test_refresh_routing_splits_news_from_dashboard() -> None:
    dashboard = RefreshRoutingHarness(0)
    dashboard._refresh_current_page()
    _assert(dashboard.calls == [('dashboard', {'force': True, 'reason': 'manual_refresh'})], 'Dashboard should still run full refresh')

    news = RefreshRoutingHarness(33)
    news._refresh_current_page()
    _assert(news.calls == [('news', {})], 'News page should run the page-local refresh path')


def main() -> None:
    test_worker_news_refresh_skips_dashboard_work()
    test_portfolio_news_cache_does_not_poison_detail_cache()
    test_ticker_specific_search_and_partial_failures()
    test_ad_hoc_ticker_news_contract_and_cancellation()
    test_general_news_sources_run_concurrently_and_dedupe()
    test_general_news_stale_fallback_and_unavailable_source()
    test_general_news_timeout_and_cancellation_contract()
    test_news_page_branches_run_concurrently()
    test_refresh_routing_splits_news_from_dashboard()
    print('News page fast refresh smoke tests passed')


if __name__ == '__main__':
    main()
