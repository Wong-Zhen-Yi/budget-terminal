from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mixins.dashboard import DashboardMixin


class DashboardNewsHarness(DashboardMixin):
    def __init__(self) -> None:
        self.tickers = ['AAA', 'BBB']

    def _sort_articles_by_newest(self, articles):
        return sorted(list(articles or []), key=lambda article: article.get('_ts', 0), reverse=True)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_dashboard_news_limit_per_visible_ticker() -> None:
    dashboard = DashboardNewsHarness()
    articles = [
        {'category': 'portfolio', 'ticker': 'AAA', 'title': 'AAA old', '_ts': 10},
        {'category': 'portfolio', 'ticker': 'AAA', 'title': 'AAA newest', '_ts': 30},
        {'category': 'portfolio', 'ticker': 'AAA', 'title': 'AAA middle', '_ts': 20},
        {'category': 'portfolio', 'ticker': 'bbb', 'title': 'BBB newest', '_ts': 25},
        {'category': 'portfolio', 'ticker': 'BBB', 'title': 'BBB old', '_ts': 5},
        {'category': 'portfolio', 'ticker': 'CCC', 'title': 'CCC ignored', '_ts': 40},
        {'category': 'macro', 'ticker': 'AAA', 'title': 'Macro ignored', '_ts': 100},
        {'category': 'other', 'ticker': 'BBB', 'title': 'Other ignored', '_ts': 90},
        {'category': 'portfolio', 'ticker': 'AAA', 'title': 'AAA no timestamp'},
    ]

    limited = dashboard._dashboard_limited_portfolio_news(articles)
    titles = [article['title'] for article in limited]

    _assert(titles == ['AAA newest', 'BBB newest', 'AAA middle', 'BBB old'], 'dashboard news should keep the two newest articles per visible ticker')
    _assert(all(article.get('category') == 'portfolio' for article in limited), 'dashboard news should exclude macro and other categories')
    _assert('CCC ignored' not in titles, 'dashboard news should exclude non-portfolio tickers')
    _assert('AAA old' not in titles, 'dashboard news should drop third and older articles for a ticker')


def main() -> None:
    test_dashboard_news_limit_per_visible_ticker()
    print('dashboard news limit smoke tests passed')


if __name__ == '__main__':
    main()
