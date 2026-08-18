from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.workers.news_sources import (
    KEYLESS_CRYPTO_NEWS_SOURCES,
    fetch_keyless_crypto_news,
)


BLOCKED_BROAD_SOURCES = {
    'CNBC Market Insider',
    'Investing.com',
    'MarketWatch',
    'MarketWatch MarketPulse',
    'Nasdaq Markets',
    'Seeking Alpha',
}


def main() -> int:
    articles = fetch_keyless_crypto_news(
        ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'COIN', 'MSTR', 'IBIT', 'ETHA', 'BITQ'],
        limit=10,
        candidate_limit=80,
    )
    print(f'Fetched {len(articles)} keyless crypto news article(s).')
    if not articles:
        raise AssertionError('Expected at least one crypto news article from keyless crypto feeds.')

    allowed_sources = set(KEYLESS_CRYPTO_NEWS_SOURCES)
    for article in articles:
        source = str(article.get('source') or '')
        ticker = article.get('ticker', 'OTHER')
        title = article.get('title', '')
        print(f'{ticker} | {source} | {title}')
        if source not in allowed_sources:
            raise AssertionError(f'Unexpected crypto news source: {source!r}')
        if source in BLOCKED_BROAD_SOURCES:
            raise AssertionError(f'Broad market source leaked into crypto news: {source!r}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
