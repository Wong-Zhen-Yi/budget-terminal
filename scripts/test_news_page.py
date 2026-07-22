from __future__ import annotations

import datetime
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from budget_terminal_app.mixins.news import NEWS_AI_PROMPT, NewsMixin


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class NewsHarness(NewsMixin):
    def __init__(self, downloads: Path) -> None:
        self.page34 = QWidget()
        self._downloads = downloads
        self.statuses: list[tuple[str, str]] = []
        self.fail_writes = False
        self.last_data = {'portfolio': {'AAA': {'price': 1.0}}, 'news': []}

    def set_theme_role(self, widget, role):
        widget.setProperty('bt_role', role)
        return widget

    def set_theme_variant(self, widget, variant):
        widget.setProperty('bt_variant', variant)
        return widget

    def theme_color(self, token):
        return {
            'accent_positive': '#2ecc71',
            'warning': '#f1c40f',
            'info': '#3498db',
            'accent': '#5b9dff',
            'text_primary': '#edf2f7',
            'text_secondary': '#b8c0cc',
            'text_muted': '#7f8a9a',
            'background_secondary': '#151f31',
            'panel_background': '#111a29',
            'panel_border': '#34425a',
            'selected_bg': '#20375c',
        }.get(token, '#b8c0cc')

    def _p34_set_status(self, text: str, status: str) -> None:
        self.statuses.append((text, status))

    def _p34_fetch_news_preview(self, article):
        self._p34_preview_request_id += 1
        self.p34_reader_body.setPlainText(f"Preview: {article.get('title', '')}")

    def _p34_downloads_directory(self) -> Path:
        self._downloads.mkdir(parents=True, exist_ok=True)
        return self._downloads

    def _p34_write_export_file(self, path: Path, text: str) -> None:
        if self.fail_writes:
            raise OSError('simulated write failure')
        super()._p34_write_export_file(path, text)


def _articles(now: float) -> list[dict]:
    return [
        {
            'category': 'portfolio',
            'ticker': 'AAA',
            'title': 'AAA older portfolio headline',
            'source': 'Portfolio Source',
            'url': 'https://example.test/portfolio-old',
            '_ts': now - 300,
        },
        {
            'category': 'portfolio',
            'ticker': 'BBB',
            'title': 'BBB newest portfolio expansion with a deliberately long complete headline that must wrap naturally inside its card without elision or a maximum-height cap',
            'source': 'Company IR',
            'url': 'https://example.test/portfolio-new',
            '_ts': now - 60,
        },
        {
            'category': 'macro',
            'ticker': 'SPY',
            'title': 'Macro inflation update',
            'source': 'Macro Source',
            'url': 'https://example.test/macro',
            '_ts': now - 30,
        },
        {
            'category': 'other',
            'ticker': 'XYZ',
            'title': 'Market guidance signal — 新闻',
            'source': 'Market Source',
            'url': 'https://example.test/market-signal',
            '_ts': now - 180,
            '_trader_score': 9,
            '_signal_tags': ['guidance', 'market move'],
        },
        {
            'category': 'other',
            'ticker': 'LOW',
            'title': 'Unscored market story',
            'source': 'Market Source',
            'url': 'https://example.test/market-low',
            '_ts': now - 90,
        },
    ]


def _ticker_search_articles(now: float) -> list[dict]:
    return [
        {
            'category': 'portfolio',
            'ticker': 'MSFT',
            'title': 'MSFT newest outside-portfolio result',
            'source': 'Search Source',
            'url': 'https://example.test/search-msft',
            '_ts': now - 10,
        },
        {
            'category': 'portfolio',
            'ticker': 'AAPL',
            'title': 'AAPL older outside-portfolio result',
            'source': 'Search Source',
            'url': 'https://example.test/search-aapl',
            '_ts': now - 20,
        },
    ]


def test_card_layout_filters_sorting_and_selection(app: QApplication, root: Path) -> None:
    harness = NewsHarness(root)
    harness.init_page34()
    harness.page34.resize(1280, 800)
    harness.page34.show()
    app.processEvents()
    _assert(harness.p34_ticker_search_section.isHidden(), 'Ticker Search should be hidden before a query')
    articles = _articles(time.time())
    harness.update_page34({'news': articles})
    app.processEvents()

    _assert(len(harness._p34_portfolio_cards) == 2, 'Portfolio Spotlight should contain both portfolio stories')
    _assert(len(harness._p34_market_cards) == 3, 'Market & Macro should combine macro and other stories')
    _assert(harness._p34_portfolio_cards[0].article['ticker'] == 'BBB', 'Portfolio cards should be newest-first')
    _assert(harness._p34_highlighted_news['ticker'] == 'BBB', 'Default selection should prefer the newest portfolio story')
    _assert(harness._p34_portfolio_cards[0].property('bt_selected') is True, 'Selected card should receive selected styling')
    _assert(harness.p34_reader_title_lbl.text().find('BBB newest') >= 0, 'Selected card should populate the reader')

    headline_label = harness._p34_portfolio_cards[0].findChild(type(harness.p34_reader_title_lbl), 'newsHeadline')
    _assert(headline_label is not None and headline_label.wordWrap(), 'Card headlines should wrap')
    _assert(headline_label.text() == articles[1]['title'], 'Card headlines must remain complete')
    _assert(headline_label.maximumHeight() >= 16_000_000, 'Card headlines must not have a maximum-height cap')

    _assert(harness._p34_columns_for_width(1100) == 3, 'Wide card areas should use three columns')
    _assert(harness._p34_columns_for_width(800) == 2, 'Medium card areas should use two columns')
    _assert(harness._p34_columns_for_width(600) == 1, 'Narrow card areas should use one column')
    harness._p34_card_columns = 0
    harness._p34_reflow_cards(1100)
    _assert(harness._p34_card_columns == 3, 'Three-column reflow should apply')
    harness._p34_reflow_cards(800)
    _assert(harness._p34_card_columns == 2, 'Two-column reflow should apply')
    harness._p34_reflow_cards(600)
    _assert(harness._p34_card_columns == 1, 'One-column reflow should apply')

    harness.p34_sort_combo.setCurrentText('Signal')
    app.processEvents()
    _assert(harness._p34_portfolio_cards[0].article['ticker'] == 'BBB', 'Signal sort should keep Portfolio Spotlight first and newest-first')
    _assert(harness._p34_market_cards[0].article['ticker'] == 'XYZ', 'Signal sort should prioritize scored market stories')

    selected_market = dict(harness._p34_market_cards[0].article)
    harness._p34_set_highlighted_news(selected_market)
    _assert(harness._p34_highlighted_news['ticker'] == 'XYZ', 'Click selection should update the active story')
    harness.update_page34({'news': articles})
    _assert(harness._p34_highlighted_news['ticker'] == 'XYZ', 'Refresh should preserve a still-visible selection')

    harness._p34_set_filter('market_macro')
    _assert(not harness.p34_portfolio_section.isVisible(), 'Market filter should hide Portfolio Spotlight')
    _assert(harness.p34_market_section.isVisible(), 'Market filter should retain Market & Macro')
    harness.p34_search_input.setText('guidance')
    app.processEvents()
    _assert(len(harness._p34_market_cards) == 1, 'Search should match headlines and signal tags')
    _assert(harness._p34_market_cards[0].article['ticker'] == 'XYZ', 'Search should retain the matching market card')
    harness.page34.close()


def test_ticker_search_section_filters_clear_and_stale(app: QApplication, root: Path) -> None:
    harness = NewsHarness(root)
    harness.init_page34()
    harness.page34.resize(1280, 800)
    harness.page34.show()
    app.processEvents()
    harness.update_page34({'news': _articles(time.time())})
    original_last_data = dict(harness.last_data)

    parsed = harness._p34_parse_ticker_search_symbols(
        ' msft, AAPL;\nBRK.B  msft  NVDA META AMZN GOOGL TSLA AMD INTC ORCL '
    )
    _assert(parsed == ['MSFT', 'AAPL', 'BRK.B', 'NVDA', 'META', 'AMZN', 'GOOGL', 'TSLA', 'AMD', 'INTC'], 'Ticker parsing should normalize, deduplicate, accept supported separators, and cap at 10')

    harness._p34_ticker_search_request_id = 7
    harness._p34_ticker_search_pending = True
    harness._p34_apply_ticker_search_result(6, {'queried_tickers': ['STALE'], 'articles': _ticker_search_articles(time.time())})
    _assert(harness._p34_ticker_search_pending is True, 'Stale ticker-search results must not clear the active request')
    _assert(harness._p34_ticker_search_articles == [], 'Stale ticker-search results must not be rendered')

    harness._p34_apply_ticker_search_result(
        7,
        {
            'queried_tickers': ['MSFT', 'AAPL', 'EMPTY', 'FAIL'],
            'articles': _ticker_search_articles(time.time()),
            'empty_tickers': ['EMPTY'],
            'failed_tickers': ['FAIL'],
        },
    )
    app.processEvents()
    _assert(not harness.p34_ticker_search_section.isHidden(), 'Ticker Search should appear after a query')
    _assert(len(harness._p34_ticker_search_cards) == 2, 'Ticker Search should render successful partial results')
    _assert(harness._p34_ticker_search_cards[0].article['ticker'] == 'MSFT', 'Ticker Search cards should be newest-first')
    _assert(all(card.article['category'] == 'search' for card in harness._p34_ticker_search_cards), 'Ticker Search should retag cached portfolio rows without mutating the cache')
    _assert(harness._p34_highlighted_news['ticker'] == 'MSFT', 'A successful ticker search should select its newest result')
    _assert('No articles: EMPTY' in harness.p34_ticker_search_meta_lbl.text(), 'Empty tickers should be disclosed in the dedicated section')
    _assert('Failed: FAIL' in harness.p34_ticker_search_meta_lbl.text(), 'Failed tickers should be disclosed without hiding successful rows')
    _assert(harness.last_data == original_last_data, 'Ticker Search must not modify dashboard or portfolio state')

    harness._p34_set_filter('portfolio')
    _assert(not harness.p34_ticker_search_section.isHidden(), 'Portfolio and Market filters must not hide Ticker Search')
    _assert(len(harness._p34_ticker_search_cards) == 2, 'Category filters must leave Ticker Search results intact')
    harness.p34_search_input.setText('MSFT')
    app.processEvents()
    _assert(len(harness._p34_ticker_search_cards) == 1, 'The existing text filter should filter Ticker Search cards')
    harness.p34_search_input.clear()
    harness._p34_clear_ticker_search()
    app.processEvents()
    _assert(harness.p34_ticker_search_section.isHidden(), 'Clear should remove the dedicated Ticker Search section')
    _assert(harness._p34_ticker_search_articles == [], 'Clear should discard session-only Ticker Search results')
    _assert(harness._p34_highlighted_news['category'] == 'portfolio', 'Clear should restore selection to the visible regular feed')
    harness.page34.close()


def test_export_contract_collisions_and_failures(root: Path) -> None:
    harness = NewsHarness(root)
    harness.init_page34()
    harness.update_page34({'news': _articles(time.time())})
    exported_at = datetime.datetime(2026, 7, 16, 14, 30, 25, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    text = harness._p34_build_export_text(now=exported_at)

    _assert(text.startswith(NEWS_AI_PROMPT + '\n'), 'News should include the skeptical AI research instruction')
    _assert('Generated at: 2026-07-16T14:30:25+08:00' in text, 'Export should include timezone-aware generation time')
    _assert('=== PORTFOLIO NEWS ===' in text and '=== MARKET & MACRO NEWS ===' in text, 'Both sections should be exported')
    _assert('Market guidance signal — 新闻' in text, 'UTF-8 headlines must be preserved')
    _assert('Signals: Guidance · Market Move' in text, 'Signal tags should be exported')
    _assert('Heuristic score: 9' in text, 'Heuristic scores should be labeled')
    _assert('TICKER SEARCH RESULTS' not in text, 'The unchanged export should omit an unused Ticker Search section')

    harness._p34_ticker_search_tickers = ['MSFT', 'AAPL']
    harness._p34_ticker_search_articles = [
        {**article, 'category': 'search'} for article in _ticker_search_articles(time.time())
    ]
    search_text = harness._p34_build_export_text(now=exported_at)
    _assert('Searched tickers: MSFT, AAPL' in search_text, 'Ticker Search export should identify the queried symbols')
    _assert('=== TICKER SEARCH RESULTS ===' in search_text, 'Ticker Search export should use a dedicated section')
    _assert('[Ticker Search] [MSFT]' in search_text, 'Ticker Search export rows should retain their distinct category')

    first = harness._p34_next_export_path(now=exported_at, directory=root)
    first.write_text('existing', encoding='utf-8')
    second = harness._p34_next_export_path(now=exported_at, directory=root)
    _assert(first.name == 'BudgetTerminal_News_2026-07-16_143025.txt', 'Primary filename should remain stable')
    _assert(second.name == 'BudgetTerminal_News_2026-07-16_143025_2.txt', 'Filename collisions should use suffixes')

    harness._p34_export_news_for_ai()
    _assert(harness.statuses[-1][1] == 'positive' and str(root) in harness.statuses[-1][0], 'Success status should include the path')

    empty = NewsHarness(root)
    empty.init_page34()
    empty._p34_export_news_for_ai()
    _assert(empty.statuses[-1] == ('No News articles to export.', 'warning'), 'Empty export should warn')

    search_only = NewsHarness(root)
    search_only.init_page34()
    search_only._p34_ticker_search_tickers = ['MSFT']
    search_only._p34_ticker_search_articles = [
        {**_ticker_search_articles(time.time())[0], 'category': 'search'}
    ]
    search_only._p34_export_news_for_ai()
    _assert(search_only.statuses[-1][1] == 'positive', 'Ticker Search results should be exportable without regular feed articles')

    harness.fail_writes = True
    original_critical = QMessageBox.critical
    QMessageBox.critical = lambda *_args, **_kwargs: None
    try:
        harness._p34_export_news_for_ai()
    finally:
        QMessageBox.critical = original_critical
    _assert(harness.statuses[-1][1] == 'negative', 'Write failure should surface a negative status')


def test_refresh_merge_and_partial_coverage(root: Path) -> None:
    harness = NewsHarness(root)
    harness.init_page34()
    harness._p34_news_refresh_request_id = 7
    harness._p34_news_refresh_pending = True
    harness._p34_apply_news_refresh_result(
        7,
        {
            'news': _articles(time.time()),
            '_news_refresh_meta': {
                'stale_sources': ['Slow Feed'],
                'failed_sources': ['Slow Feed', 'Missing Feed'],
                'failed_tickers': ['FAIL'],
            },
        },
    )
    _assert(harness.last_data['portfolio'] == {'AAA': {'price': 1.0}}, 'News-only refresh must preserve dashboard data')
    _assert(harness._p34_news_refresh_pending is False, 'Applied refresh should clear pending state')
    expected = 'News refreshed: 5 article(s). (1 stale source(s), 1 unavailable source(s), 1 ticker search failure(s))'
    _assert(harness.statuses[-1] == (expected, 'warning'), 'Partial coverage should remain explicit')


def main() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        test_card_layout_filters_sorting_and_selection(app, root)
        test_ticker_search_section_filters_clear_and_stale(app, root)
        test_export_contract_collisions_and_failures(root)
        test_refresh_merge_and_partial_coverage(root)
    print('News page smoke tests passed')


if __name__ == '__main__':
    main()
