from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.workers.data import OTHER_NEWS_CANDIDATE_LIMIT, OTHER_NEWS_FOCUS_TICKERS, OTHER_NEWS_LIMIT
from budget_terminal_app.workers.news_sources import fetch_keyless_trader_news


def main() -> int:
    articles = fetch_keyless_trader_news(
        OTHER_NEWS_FOCUS_TICKERS,
        limit=OTHER_NEWS_LIMIT,
        candidate_limit=OTHER_NEWS_CANDIDATE_LIMIT,
    )
    print(f'Fetched {len(articles)} keyless trader news article(s).')
    for article in articles:
        score = article.get('_trader_score', 0)
        ticker = article.get('ticker', 'OTHER')
        source = article.get('source', '')
        title = article.get('title', '')
        print(f'[{score:02}] {ticker} | {source} | {title}')
    return 0 if articles else 1


if __name__ == '__main__':
    raise SystemExit(main())
