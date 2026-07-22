from __future__ import annotations

import gc
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.dependencies import pd


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager(Path(tmp) / 'cache.db')
        _assert(cache._cache_table_name('cache', 'AAPL', '1d') == 'cache_AAPL_1d', 'simple cache table names should stay stable')
        special_name = cache._cache_table_name('cache', '0700.HK', '1d')
        _assert('.' not in special_name and special_name.startswith('cache_0700_HK_'), 'special tickers should get safe table names')

        dates = pd.to_datetime(['2026-01-02', '2026-01-05'])
        price_df = pd.DataFrame({'Close': [10.0, 10.5]}, index=dates)
        price_df.index.name = 'Date'
        cache.save_data('0700.HK', '1d', price_df)
        loaded_price = cache.get_data('0700.HK', '1d')
        _assert(loaded_price is not None and len(loaded_price) == 2, 'special ticker price cache should round trip')

        chain_df = pd.DataFrame({
            'contractSymbol': ['SHOP260619C00100000'],
            'strike': [100.0],
            'lastPrice': [5.25],
            'type': ['Call'],
        })
        cache.save_options_chain('SHOP.TO', '2026-06-19', chain_df)
        loaded_chain = cache.get_options_chain('SHOP.TO', '2026-06-19')
        _assert(loaded_chain is not None and loaded_chain.iloc[0]['contractSymbol'] == 'SHOP260619C00100000', 'special ticker options cache should round trip')
        del loaded_price, loaded_chain, price_df, chain_df, cache
        gc.collect()
    print('cache identifier smoke tests passed')


if __name__ == '__main__':
    main()
