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
    universe = {'AI', 'BTC', 'COST', 'ETH', 'NET', 'NOW', 'NVDA', 'SOL', 'T', 'XRP'}
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

    bitcoin_context = _extract_tickers(
        'Bitcoin ETF inflows rise as BTC holds above support',
        'Spot bitcoin funds drew assets.',
        [],
        '',
        universe,
    )
    _assert('BTC' in bitcoin_context, 'BTC should match Bitcoin and BTC crypto context')

    ethereum_context = _extract_tickers(
        'Ethereum staking queue grows after ether rally',
        'ETH network activity improved.',
        [],
        '',
        universe,
    )
    _assert('ETH' in ethereum_context, 'ETH should match Ethereum, ether, and ETH crypto context')

    solana_context = _extract_tickers(
        'Solana validators approve upgrade',
        'SOL network activity rises.',
        [],
        '',
        universe,
    )
    _assert('SOL' in solana_context, 'SOL should match Solana and SOL crypto context')

    xrp_context = _extract_tickers(
        'Ripple expands custody tools for institutions',
        'XRP Ledger developers proposed a DeFi security upgrade.',
        [],
        '',
        universe,
    )
    _assert('XRP' in xrp_context, 'XRP should match Ripple and XRP crypto context')
    print('news ticker extraction smoke tests passed')


if __name__ == '__main__':
    main()
