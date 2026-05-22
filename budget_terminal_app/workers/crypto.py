from __future__ import annotations

from typing import Any

from ..dependencies import *
from .news_sources import fetch_keyless_trader_news


class CryptoMarketWorker(QObject):
    """Fetch Crypto page market data without blocking the Qt UI thread."""

    partial = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    CRYPTO_TICKERS: tuple[tuple[str, str, str], ...] = (
        ('BTC', 'BTC-USD', 'Bitcoin'),
        ('ETH', 'ETH-USD', 'Ethereum'),
        ('SOL', 'SOL-USD', 'Solana'),
        ('XRP', 'XRP-USD', 'XRP'),
        ('BNB', 'BNB-USD', 'BNB'),
    )
    PROXY_TICKERS: tuple[tuple[str, str, str], ...] = (
        ('COIN', 'COIN', 'Exchange'),
        ('MSTR', 'MSTR', 'BTC treasury'),
        ('BMNR', 'BMNR', 'Crypto treasury equity'),
        ('IBIT', 'IBIT', 'Spot BTC ETF'),
        ('ETHA', 'ETHA', 'Spot ETH ETF'),
        ('BITQ', 'BITQ', 'Crypto equity ETF'),
    )
    COINGECKO_IDS: dict[str, str] = {
        'BTC': 'bitcoin',
        'ETH': 'ethereum',
        'SOL': 'solana',
        'XRP': 'ripple',
        'BNB': 'binancecoin',
    }
    TOP_HEATMAP_LIMIT = 30

    def __init__(self) -> None:
        super().__init__()

    def run(self) -> None:
        try:
            fetched_at = datetime.datetime.now().isoformat(timespec='seconds')
            progress = {
                'heatmap': 'pending',
                'quotes': 'pending',
                'market': 'pending',
                'news': 'pending',
            }
            payload: dict[str, Any] = {'fetched_at': fetched_at, 'progress': dict(progress)}

            try:
                top_crypto_rows = self._fetch_top_crypto_heatmap()
                heatmap = self._build_heatmap_payload(top_crypto_rows, fetched_at)
                progress['heatmap'] = 'loaded' if heatmap.get('tiles') else 'unavailable'
                payload.update({'heatmap': heatmap, 'progress': dict(progress)})
                self.partial.emit(dict(payload))
            except Exception as exc:
                logger.info('Crypto heatmap stage failed: %s', exc)
                progress['heatmap'] = 'unavailable'
                payload.update({'heatmap': self._build_heatmap_payload([], fetched_at), 'progress': dict(progress)})
                self.partial.emit(dict(payload))

            try:
                quotes = self._fetch_quotes()
                progress['quotes'] = 'loaded' if quotes else 'unavailable'
                if quotes and progress.get('heatmap') != 'loaded':
                    fallback_heatmap = self._build_heatmap_payload(self._build_heatmap_from_quotes(quotes), fetched_at)
                    if fallback_heatmap.get('tiles'):
                        progress['heatmap'] = 'loaded'
                        payload['heatmap'] = fallback_heatmap
                payload.update({'quotes': quotes, 'progress': dict(progress)})
                self.partial.emit(dict(payload))
            except Exception as exc:
                logger.info('Crypto quote stage failed: %s', exc)
                progress['quotes'] = 'unavailable'
                payload.update({'quotes': {}, 'progress': dict(progress)})
                self.partial.emit(dict(payload))

            try:
                global_data = self._fetch_global_market()
                fear_greed = self._fetch_crypto_fear_greed()
                progress['market'] = 'loaded' if global_data or fear_greed else 'unavailable'
                payload.update({'global': global_data, 'fear_greed': fear_greed, 'progress': dict(progress)})
                self.partial.emit(dict(payload))
            except Exception as exc:
                logger.info('Crypto market status stage failed: %s', exc)
                progress['market'] = 'unavailable'
                payload.update({'global': {}, 'fear_greed': {}, 'progress': dict(progress)})
                self.partial.emit(dict(payload))

            try:
                news = self._fetch_news()
                progress['news'] = 'loaded' if news else 'unavailable'
                payload.update({'news': news, 'progress': dict(progress)})
                self.partial.emit(dict(payload))
            except Exception as exc:
                logger.info('Crypto news stage failed: %s', exc)
                progress['news'] = 'unavailable'
                payload.update({'news': [], 'progress': dict(progress)})
                self.partial.emit(dict(payload))

            self.finished.emit(payload)
        except Exception as exc:
            logger.exception('CryptoMarketWorker error.')
            self.error.emit(str(exc))

    def _fetch_quotes(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        crypto_quotes = self._fetch_coingecko_quotes()
        for label, symbol, name in self.CRYPTO_TICKERS:
            fallback = self._fetch_quote(symbol)
            live = crypto_quotes.get(label, {})
            quote = {
                'price': self._first_number(live.get('price'), fallback.get('price')),
                'change_pct': self._first_number(live.get('change_pct'), fallback.get('change_pct')),
                'volume': self._first_number(live.get('volume'), fallback.get('volume')),
                'market_cap': self._first_number(live.get('market_cap'), fallback.get('market_cap')),
                'source': live.get('source') or fallback.get('source') or 'Yahoo Finance',
            }
            quote.update({'label': label, 'symbol': symbol, 'name': name})
            rows[label] = quote
        for label, symbol, name in self.PROXY_TICKERS:
            quote = self._fetch_quote(symbol)
            quote.update({'label': label, 'symbol': symbol, 'name': name})
            rows[label] = quote
        return rows

    def _fetch_coingecko_quotes(self) -> dict[str, dict[str, Any]]:
        ids = ','.join(self.COINGECKO_IDS.values())
        try:
            response = requests.get(
                'https://api.coingecko.com/api/v3/coins/markets',
                params={
                    'vs_currency': 'usd',
                    'ids': ids,
                    'order': 'market_cap_desc',
                    'per_page': len(self.COINGECKO_IDS),
                    'page': 1,
                    'sparkline': 'false',
                    'price_change_percentage': '24h',
                },
                headers={'User-Agent': 'BudgetTerminal/1.0 crypto-page'},
                timeout=12,
            )
            response.raise_for_status()
            by_id = {str(row.get('id') or ''): row for row in response.json() or [] if isinstance(row, dict)}
        except Exception as exc:
            logger.info('CoinGecko crypto quote fetch failed: %s', exc)
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for label, coin_id in self.COINGECKO_IDS.items():
            row = by_id.get(coin_id) or {}
            if not row:
                continue
            rows[label] = {
                'price': self._first_number(row.get('current_price')),
                'change_pct': self._first_number(
                    row.get('price_change_percentage_24h_in_currency'),
                    row.get('price_change_percentage_24h'),
                ),
                'volume': self._first_number(row.get('total_volume')),
                'market_cap': self._first_number(row.get('market_cap')),
                'source': 'CoinGecko',
            }
        return rows

    def _fetch_top_crypto_heatmap(self) -> list[dict[str, Any]]:
        try:
            response = requests.get(
                'https://api.coingecko.com/api/v3/coins/markets',
                params={
                    'vs_currency': 'usd',
                    'order': 'market_cap_desc',
                    'per_page': self.TOP_HEATMAP_LIMIT,
                    'page': 1,
                    'sparkline': 'false',
                    'price_change_percentage': '24h',
                },
                headers={'User-Agent': 'BudgetTerminal/1.0 crypto-page'},
                timeout=12,
            )
            response.raise_for_status()
            rows = response.json() or []
        except Exception as exc:
            logger.info('CoinGecko top crypto heatmap fetch failed: %s', exc)
            return []

        tiles: list[dict[str, Any]] = []
        for index, row in enumerate(rows[:self.TOP_HEATMAP_LIMIT], start=1):
            if not isinstance(row, dict):
                continue
            symbol = str(row.get('symbol') or '').strip().upper()
            name = str(row.get('name') or '').strip()
            if not symbol:
                continue
            rank_number = self._first_number(row.get('market_cap_rank'), index)
            tiles.append({
                'rank': int(rank_number) if rank_number is not None else index,
                'symbol': symbol,
                'name': name or symbol,
                'price': self._first_number(row.get('current_price')),
                'change_pct': self._first_number(
                    row.get('price_change_percentage_24h_in_currency'),
                    row.get('price_change_percentage_24h'),
                ),
                'market_cap': self._first_number(row.get('market_cap')),
                'volume': self._first_number(row.get('total_volume')),
                'source': 'CoinGecko',
            })
        return tiles

    def _fetch_quote(self, symbol: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            'price': None,
            'change_pct': None,
            'volume': None,
            'market_cap': None,
            'source': 'Yahoo Finance',
        }
        try:
            with YF_LOCK:
                ticker = yf.Ticker(symbol)
                history = ticker.history(period='5d', interval='1d')
                fast_info = getattr(ticker, 'fast_info', {}) or {}
            if history is not None and not history.empty and 'Close' in history:
                closes = pd.to_numeric(history['Close'], errors='coerce').dropna()
                if len(closes) >= 1:
                    result['price'] = float(closes.iloc[-1])
                if len(closes) >= 2 and float(closes.iloc[-2]) != 0:
                    result['change_pct'] = (float(closes.iloc[-1]) - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100.0
                if 'Volume' in history:
                    volumes = pd.to_numeric(history['Volume'], errors='coerce').dropna()
                    if len(volumes) >= 1:
                        result['volume'] = float(volumes.iloc[-1])
            result['price'] = self._first_number(
                result.get('price'),
                self._fast_info_value(fast_info, 'last_price'),
                self._fast_info_value(fast_info, 'lastPrice'),
            )
            result['market_cap'] = self._first_number(
                self._fast_info_value(fast_info, 'market_cap'),
                self._fast_info_value(fast_info, 'marketCap'),
            )
        except Exception as exc:
            logger.info('Crypto quote fetch failed for %s: %s', symbol, exc)
        return result

    def _build_heatmap_payload(self, tiles: list[dict[str, Any]], updated_at: str) -> dict[str, Any]:
        normalized_tiles = []
        for index, tile in enumerate(tiles[:self.TOP_HEATMAP_LIMIT], start=1):
            if not isinstance(tile, dict):
                continue
            normalized_tiles.append({
                'rank': tile.get('rank') or index,
                'symbol': str(tile.get('symbol') or '').strip().upper(),
                'name': str(tile.get('name') or tile.get('symbol') or '').strip(),
                'price': self._first_number(tile.get('price')),
                'change_pct': self._first_number(tile.get('change_pct')),
                'market_cap': self._first_number(tile.get('market_cap')),
                'volume': self._first_number(tile.get('volume')),
                'source': str(tile.get('source') or 'CoinGecko'),
            })
        return {
            'tiles': normalized_tiles,
            'coverage': {
                'loaded': len(normalized_tiles),
                'total': self.TOP_HEATMAP_LIMIT,
            },
            'updated_at': updated_at,
        }

    def _build_heatmap_from_quotes(self, quotes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        tiles: list[dict[str, Any]] = []
        for index, (label, _symbol, name) in enumerate(self.CRYPTO_TICKERS, start=1):
            quote = quotes.get(label, {}) if isinstance(quotes.get(label), dict) else {}
            if not quote:
                continue
            tiles.append({
                'rank': index,
                'symbol': label,
                'name': name,
                'price': self._first_number(quote.get('price')),
                'change_pct': self._first_number(quote.get('change_pct')),
                'market_cap': self._first_number(quote.get('market_cap')),
                'volume': self._first_number(quote.get('volume')),
                'source': quote.get('source') or 'Yahoo Finance',
            })
        return tiles

    @staticmethod
    def _positive_number(value: Any) -> float | None:
        try:
            number = float(value)
        except Exception:
            return None
        if math.isfinite(number) and number > 0:
            return number
        return None

    @staticmethod
    def _fast_info_value(fast_info: Any, key: str) -> Any:
        try:
            return fast_info[key]
        except Exception:
            return getattr(fast_info, key, None)

    @staticmethod
    def _first_number(*values: Any) -> float | None:
        for value in values:
            try:
                if value is None:
                    continue
                number = float(value)
                if math.isfinite(number):
                    return number
            except Exception:
                continue
        return None

    def _fetch_global_market(self) -> dict[str, Any]:
        try:
            response = requests.get(
                'https://api.coingecko.com/api/v3/global',
                headers={'User-Agent': 'BudgetTerminal/1.0 crypto-page'},
                timeout=12,
            )
            response.raise_for_status()
            data = response.json().get('data', {})
            cap = data.get('total_market_cap', {}).get('usd')
            volume = data.get('total_volume', {}).get('usd')
            change = data.get('market_cap_change_percentage_24h_usd')
            return {
                'market_cap': self._first_number(cap),
                'volume_24h': self._first_number(volume),
                'change_pct': self._first_number(change),
                'btc_dominance': self._first_number(data.get('market_cap_percentage', {}).get('btc')),
            }
        except Exception as exc:
            logger.info('CoinGecko global crypto fetch failed: %s', exc)
            return {}

    def _fetch_crypto_fear_greed(self) -> dict[str, Any]:
        try:
            response = requests.get(
                'https://api.alternative.me/fng/?limit=1',
                headers={'User-Agent': 'BudgetTerminal/1.0 crypto-page'},
                timeout=12,
            )
            response.raise_for_status()
            data = response.json().get('data') or []
            latest = data[0] if data else {}
            value = self._first_number(latest.get('value'))
            timestamp = latest.get('timestamp')
            ts_text = ''
            if timestamp:
                try:
                    ts_text = datetime.datetime.fromtimestamp(int(timestamp)).strftime('%b %d')
                except Exception:
                    ts_text = str(timestamp)
            return {
                'value': value,
                'classification': str(latest.get('value_classification') or '--'),
                'timestamp': ts_text,
                'source': 'Alternative.me',
            }
        except Exception as exc:
            logger.info('Crypto Fear & Greed fetch failed: %s', exc)
            return {}

    def _fetch_news(self) -> list[dict[str, Any]]:
        try:
            return fetch_keyless_trader_news(
                ['BTC', 'ETH', 'SOL', 'COIN', 'MSTR', 'BMNR', 'IBIT', 'ETHA', 'BITQ'],
                limit=10,
                candidate_limit=80,
            )
        except Exception as exc:
            logger.info('Crypto news fetch failed: %s', exc)
            return []
