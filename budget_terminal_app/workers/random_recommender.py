from __future__ import annotations

import datetime
import random
from typing import Any

from ..dependencies import *


class RandomStockWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    _MIN_MARKET_CAP = 1_000_000_000
    _MIN_AVG_VOLUME = 1_000_000
    _MAX_ATTEMPTS = 5

    def _query(self) -> Any:
        return yf.EquityQuery('and', [
            yf.EquityQuery('eq', ['region', 'us']),
            yf.EquityQuery('gt', ['intradaymarketcap', self._MIN_MARKET_CAP]),
            yf.EquityQuery('gt', ['avgdailyvol3m', self._MIN_AVG_VOLUME]),
        ])

    def _screen_total(self, query: Any) -> int:
        response = yf.screen(query, size=1, offset=0, sortField='ticker', sortAsc=True)
        if not isinstance(response, dict):
            return 0
        try:
            return max(int(response.get('total', 0) or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _screen_quote(self, query: Any, total: int) -> dict[str, Any]:
        if total <= 0:
            return {}
        offset = random.randint(0, max(total - 1, 0))
        response = yf.screen(query, size=1, offset=offset, sortField='ticker', sortAsc=True)
        if not isinstance(response, dict):
            return {}
        quotes = response.get('quotes') or []
        if not quotes or not isinstance(quotes[0], dict):
            return {}
        return dict(quotes[0])

    def _fallback_info_from_quote(self, symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
        return {
            'symbol': symbol,
            'shortName': quote.get('shortName') or quote.get('displayName') or symbol,
            'longName': quote.get('longName') or quote.get('shortName') or symbol,
            'regularMarketPrice': quote.get('regularMarketPrice'),
            'currentPrice': quote.get('regularMarketPrice'),
            'previousClose': quote.get('regularMarketPreviousClose'),
            'marketCap': quote.get('marketCap'),
            'trailingPE': quote.get('trailingPE'),
            'forwardPE': quote.get('forwardPE'),
            'beta': quote.get('beta'),
            'dividendYield': quote.get('dividendYield'),
            'averageVolume': quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'),
            'fiftyTwoWeekLow': quote.get('fiftyTwoWeekLow'),
            'fiftyTwoWeekHigh': quote.get('fiftyTwoWeekHigh'),
            'exchange': quote.get('exchange') or quote.get('fullExchangeName'),
            'currency': quote.get('currency'),
            'targetMeanPrice': quote.get('targetMeanPrice'),
        }

    def _load_info(self, ticker_obj: Any, symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
        try:
            info = ticker_obj.info
            if not isinstance(info, dict):
                info = {}
        except Exception as exc:
            if is_yahoo_unauthorized_error(exc):
                logger.info('Yahoo refused random roll metadata for %s; using screener quote fallback.', symbol)
            else:
                logger.info('Random roll metadata fetch failed for %s: %s', symbol, exc)
            info = {}
        fallback = self._fallback_info_from_quote(symbol, quote)
        for key, value in fallback.items():
            if info.get(key) in (None, '', 'N/A') and value not in (None, '', 'N/A'):
                info[key] = value
        return info

    def _valid_candidate(self, symbol: str, info: dict[str, Any], quote: dict[str, Any]) -> bool:
        if not symbol:
            return False
        name = info.get('longName') or info.get('shortName') or quote.get('longName') or quote.get('shortName')
        price = (
            info.get('regularMarketPrice')
            or info.get('currentPrice')
            or quote.get('regularMarketPrice')
            or quote.get('regularMarketPreviousClose')
        )
        return bool(name and price not in (None, '', 'N/A'))

    def _parse_news_item(self, item: Any, symbol: str) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        content = item.get('content') or {}
        title = str(content.get('title') or item.get('title') or '').strip()
        if not title:
            return None
        source = str(content.get('provider', {}).get('displayName') or item.get('publisher') or 'N/A').strip() or 'N/A'
        pub_date = content.get('pubDate') or item.get('providerPublishTime') or ''
        time_text = '--:--'
        timestamp = 0.0
        if isinstance(pub_date, (int, float)) and not isinstance(pub_date, bool):
            timestamp = float(pub_date)
            try:
                time_text = datetime.datetime.fromtimestamp(float(pub_date)).strftime('%H:%M')
            except Exception:
                pass
        elif pub_date:
            try:
                parsed = datetime.datetime.fromisoformat(str(pub_date).replace('Z', '+00:00'))
                time_text = parsed.strftime('%H:%M')
                timestamp = parsed.timestamp()
            except Exception:
                time_text = str(pub_date)[:10]
        url_data = content.get('canonicalUrl') or content.get('clickThroughUrl') or item.get('link') or ''
        url = url_data.get('url', '') if isinstance(url_data, dict) else str(url_data or '')
        return {
            'ticker': symbol,
            'title': title,
            'source': source,
            'time': time_text,
            'url': url,
            'category': 'stock',
            '_ts': timestamp,
        }

    def _load_news(self, ticker_obj: Any, symbol: str) -> list[dict[str, Any]]:
        try:
            raw_items = list(getattr(ticker_obj, 'news', []) or [])[:12]
        except Exception:
            return []
        articles = []
        for item in raw_items:
            article = self._parse_news_item(item, symbol)
            if article is not None:
                articles.append(article)
        return articles

    def _load_chart_history(self, ticker_obj: Any) -> dict[str, Any]:
        try:
            history = ticker_obj.history(period='1y', interval='1d')
        except Exception:
            return {'dates': [], 'closes': []}
        if history is None or history.empty or 'Close' not in history.columns:
            return {'dates': [], 'closes': []}
        closes = history['Close'].dropna()
        if closes.empty:
            return {'dates': [], 'closes': []}
        dates = []
        values = []
        for index_value, close_value in closes.items():
            try:
                numeric = float(close_value)
            except Exception:
                continue
            if not math.isfinite(numeric):
                continue
            try:
                date_text = pd.Timestamp(index_value).strftime('%Y-%m-%d')
            except Exception:
                date_text = str(index_value)[:10]
            dates.append(date_text)
            values.append(numeric)
        return {'dates': dates, 'closes': values}

    def _load_top_option_for_expiry(self, symbol: str, expiry: str) -> dict[str, Any] | None:
        try:
            chain = yf.Ticker(symbol).option_chain(expiry)
            calls = chain.calls.copy()
            puts = chain.puts.copy()
        except Exception as exc:
            logger.info('Roll top options fetch failed for %s %s: %s', symbol, expiry, exc)
            return None
        frames = []
        if calls is not None and not calls.empty:
            calls['type'] = 'Call'
            frames.append(calls)
        if puts is not None and not puts.empty:
            puts['type'] = 'Put'
            frames.append(puts)
        if not frames:
            return None
        options_df = pd.concat(frames, ignore_index=True)
        if options_df is None or options_df.empty:
            return None
        options_df['ticker'] = symbol
        options_df['expiration'] = expiry
        for column in ('strike', 'lastPrice', 'volume', 'openInterest', 'impliedVolatility'):
            if column not in options_df.columns:
                options_df[column] = 0.0
            options_df[column] = pd.to_numeric(options_df[column], errors='coerce')
        options_df['volume'] = options_df['volume'].fillna(0.0)
        options_df['openInterest'] = options_df['openInterest'].fillna(0.0)
        if 'type' not in options_df.columns:
            options_df['type'] = ''
        top_row = options_df.sort_values(by=['volume', 'openInterest'], ascending=False, na_position='last').head(1)
        if top_row.empty:
            return None
        row = top_row.iloc[0]
        return {
            'ticker': symbol,
            'type': str(row.get('type', '') or ''),
            'expiration': expiry,
            'strike': row.get('strike'),
            'lastPrice': row.get('lastPrice'),
            'volume': row.get('volume'),
            'openInterest': row.get('openInterest'),
            'impliedVolatility': row.get('impliedVolatility'),
        }

    def _load_top_options(self, ticker_obj: Any, symbol: str) -> tuple[list[dict[str, Any]], str]:
        try:
            expiries = [str(expiry or '').strip() for expiry in list(ticker_obj.options or []) if str(expiry or '').strip()]
        except Exception as exc:
            logger.info('Roll top options expirations unavailable for %s: %s', symbol, exc)
            return [], 'Top options unavailable: expirations could not be loaded.'
        if not expiries:
            return [], 'No options expirations were available for this ticker.'

        records_by_expiry = {}
        failed_count = 0
        max_workers = max(1, min(4, len(expiries)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._load_top_option_for_expiry, symbol, expiry): expiry
                for expiry in expiries
            }
            for future, expiry in futures.items():
                try:
                    record = future.result()
                except Exception as exc:
                    logger.info('Roll top options worker failed for %s %s: %s', symbol, expiry, exc)
                    record = None
                if record is None:
                    failed_count += 1
                    continue
                records_by_expiry[expiry] = record

        records = [records_by_expiry[expiry] for expiry in expiries if expiry in records_by_expiry]
        if not records:
            return [], 'Top options unavailable: all option-chain loads failed.'
        status = ''
        if failed_count >= len(expiries):
            status = 'Top options unavailable: all option-chain loads failed.'
        return records, status

    def run(self) -> None:
        try:
            query = self._query()
            total = self._screen_total(query)
            if total <= 0:
                self.error.emit('No liquid US equity candidates were returned by yfinance.')
                return
            last_symbol = ''
            for _attempt in range(self._MAX_ATTEMPTS):
                quote = self._screen_quote(query, total)
                symbol = str(quote.get('symbol') or '').upper().strip()
                last_symbol = symbol or last_symbol
                if not symbol:
                    continue
                ticker_obj = yf.Ticker(symbol)
                info = self._load_info(ticker_obj, symbol, quote)
                if not self._valid_candidate(symbol, info, quote):
                    continue
                website = str(info.get('website') or '').strip()
                ir_url = str(info.get('irWebsite') or '').strip()
                if not ir_url:
                    ir_url = f'https://www.google.com/search?q={symbol}+investor+relations'
                top_options, top_options_status = self._load_top_options(ticker_obj, symbol)
                self.finished.emit({
                    'symbol': symbol,
                    'quote': quote,
                    'info': info,
                    'news': self._load_news(ticker_obj, symbol),
                    'chart_history': self._load_chart_history(ticker_obj),
                    'top_options': top_options,
                    'top_options_status': top_options_status,
                    'website': website,
                    'ir_url': ir_url,
                    'source': 'yfinance',
                    'universe_total': total,
                })
                return
            suffix = f' Last attempted: {last_symbol}.' if last_symbol else ''
            self.error.emit(f'Could not find a random candidate with usable company and price data.{suffix}')
        except Exception as exc:
            self.error.emit(f'Random roll failed: {exc}')
