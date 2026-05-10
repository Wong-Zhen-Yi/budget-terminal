from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.workers.news_sources import _extract_tickers


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    universe = {'AI', 'COST', 'NET', 'NOW', 'NVDA', 'T'}
    false_cost = _extract_tickers(
        'Cloudflare expands cost controls as demand rises',
        'The company said lower bandwidth cost helped margins.',
        [],
        'https://example.test/markets/cloudflare-cost-controls',
        universe,
    )
    _assert('COST' not in false_cost, 'plain cost prose and URL slugs should not tag COST')

    url_only = _extract_tickers(
        'Retailers move before holiday season',
        '',
        [],
        'https://example.test/stocks/COST',
        universe,
    )
    _assert('COST' not in url_only, 'bare tickers should not be inferred from URLs')

    costco_context = _extract_tickers(
        'Costco Wholesale reports stronger sales',
        'Shares of Costco rose after monthly comparable sales improved.',
        [],
        '',
        universe,
    )
    _assert('COST' in costco_context, 'COST should match when Costco context is present')

    explicit_tags = _extract_tickers(
        '$COST and NYSE: NOW rise after analyst upgrades',
        'Nvidia (NVDA) also gained.',
        [],
        '',
        universe,
    )
    _assert({'COST', 'NOW', 'NVDA'}.issubset(set(explicit_tags)), 'explicit ticker evidence should still match')
    print('news ticker extraction smoke tests passed')


if __name__ == '__main__':
    main()
