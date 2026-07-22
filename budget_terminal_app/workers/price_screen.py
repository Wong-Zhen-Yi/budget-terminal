from __future__ import annotations

from typing import Any

from ..dependencies import *


class PriceScreenWorker(QObject):
    """Fetch the largest major-exchange US equities inside a price range."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    _PAGE_SIZE = 250
    _MAJOR_EXCHANGES = ('NYQ', 'NMS', 'NGM', 'NCM', 'ASE')
    _EXCHANGE_LABELS = {
        'NYQ': 'NYSE',
        'NMS': 'Nasdaq',
        'NGM': 'Nasdaq',
        'NCM': 'Nasdaq',
        'ASE': 'NYSE American',
    }

    def __init__(self, minimum_price: float, maximum_price: float, limit: int = 100) -> None:
        super().__init__()
        self.minimum_price = float(minimum_price)
        self.maximum_price = float(maximum_price)
        self.limit = max(1, int(limit))

    def run(self) -> None:
        try:
            self.finished.emit(self.fetch())
        except Exception as exc:
            logger.error('PriceScreenWorker error: %s', exc)
            self.error.emit(str(exc))

    def fetch(self) -> dict[str, Any]:
        self._validate_range()
        query = self._query()
        rows_by_symbol: dict[str, dict[str, Any]] = {}
        candidate_count = 0
        offset = 0

        while len(rows_by_symbol) < self.limit:
            response = self._screen_page(query, offset)
            if not isinstance(response, dict):
                break
            try:
                candidate_count = max(candidate_count, int(response.get('total') or 0))
            except (TypeError, ValueError):
                pass
            quotes = response.get('quotes') or []
            if not isinstance(quotes, list) or not quotes:
                break
            for quote in quotes:
                row = self._row_from_quote(quote)
                if row is None:
                    continue
                symbol = str(row['ticker'])
                existing = rows_by_symbol.get(symbol)
                if existing is None or float(row['market_cap']) > float(existing['market_cap']):
                    rows_by_symbol[symbol] = row
            offset += self._PAGE_SIZE
            if candidate_count and offset >= candidate_count:
                break
            if len(quotes) < self._PAGE_SIZE:
                break

        rows = sorted(
            rows_by_symbol.values(),
            key=lambda row: (-float(row['market_cap']), float(row['price']), str(row['ticker'])),
        )[:self.limit]
        return {
            'rows': rows,
            'source': 'Yahoo Finance',
            'as_of': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'candidate_count': candidate_count,
            'minimum_price': self.minimum_price,
            'maximum_price': self.maximum_price,
        }

    def _validate_range(self) -> None:
        if not math.isfinite(self.minimum_price) or not math.isfinite(self.maximum_price):
            raise ValueError('Price range must contain finite values.')
        if self.minimum_price <= 0 or self.maximum_price <= 0:
            raise ValueError('Price range must be greater than $0.')
        if self.minimum_price > self.maximum_price:
            raise ValueError('Minimum price cannot exceed maximum price.')

    def _query(self) -> Any:
        exchange_query = yf.EquityQuery(
            'or',
            [yf.EquityQuery('eq', ['exchange', exchange]) for exchange in self._MAJOR_EXCHANGES],
        )
        return yf.EquityQuery('and', [
            yf.EquityQuery('eq', ['region', 'us']),
            yf.EquityQuery('gte', ['intradayprice', self.minimum_price]),
            yf.EquityQuery('lte', ['intradayprice', self.maximum_price]),
            exchange_query,
        ])

    def _screen_page(self, query: Any, offset: int) -> dict[str, Any]:
        with YF_LOCK:
            response = yf.screen(
                query,
                size=self._PAGE_SIZE,
                offset=int(offset),
                sortField='intradaymarketcap',
                sortAsc=False,
            )
        return response if isinstance(response, dict) else {}

    def _row_from_quote(self, quote: Any) -> dict[str, Any] | None:
        if not isinstance(quote, dict):
            return None
        if str(quote.get('quoteType') or '').upper().strip() != 'EQUITY':
            return None
        exchange_code = str(quote.get('exchange') or '').upper().strip()
        if exchange_code not in self._MAJOR_EXCHANGES:
            return None
        symbol = str(quote.get('symbol') or '').upper().strip()
        if not symbol:
            return None
        price = self._first_positive_number(
            quote.get('regularMarketPrice'),
            quote.get('intradayprice'),
            quote.get('eodprice'),
        )
        market_cap = self._first_positive_number(
            quote.get('marketCap'),
            quote.get('intradaymarketcap'),
            quote.get('lastclosemarketcap.lasttwelvemonths'),
        )
        if price is None or market_cap is None:
            return None
        if price < self.minimum_price or price > self.maximum_price:
            return None
        name = str(
            quote.get('longName')
            or quote.get('shortName')
            or quote.get('displayName')
            or symbol
        ).strip()
        return {
            'ticker': symbol,
            'name': name or symbol,
            'exchange': self._EXCHANGE_LABELS.get(exchange_code, exchange_code),
            'price': price,
            'market_cap': market_cap,
        }

    @staticmethod
    def _first_positive_number(*values: Any) -> float | None:
        for value in values:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric) and numeric > 0:
                return numeric
        return None
