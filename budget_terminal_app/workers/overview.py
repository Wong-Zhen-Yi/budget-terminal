from __future__ import annotations

from typing import Any

from ..dependencies import *


class TradingVolumeWorker(QObject):
    """Fetch high dollar-volume US equities for the Overview page."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    _LIMIT = 100
    _SCREEN_PAGE_SIZE = 250
    _SCREEN_OFFSETS = (0, 250, 500, 750)

    def run(self) -> None:
        try:
            self.finished.emit(self.fetch())
        except Exception as ex:
            logger.error('TradingVolumeWorker error: %s', ex)
            self.error.emit(str(ex))

    def fetch(self) -> dict[str, Any]:
        quotes = self._fetch_screen_quotes()
        rows = self._rows_from_quotes(quotes)
        rows.sort(key=lambda row: float(row.get('one_day_dollar_volume') or 0.0), reverse=True)
        rows = rows[:self._LIMIT]
        self._merge_trading_volume_history(rows)
        rows.sort(key=lambda row: float(row.get('one_day_dollar_volume') or 0.0), reverse=True)
        for row in rows:
            row.pop('_avg_share_volume', None)
            row.pop('_price', None)
        return {
            'rows': rows,
            'as_of': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'source': 'Yahoo Finance',
        }

    def _query(self) -> Any:
        return yf.EquityQuery('and', [
            yf.EquityQuery('eq', ['region', 'us']),
            yf.EquityQuery('gt', ['dayvolume', 0]),
            yf.EquityQuery('gt', ['intradayprice', 0]),
        ])

    def _fetch_screen_quotes(self) -> list[dict[str, Any]]:
        query = self._query()
        by_symbol: dict[str, dict[str, Any]] = {}
        sort_fields = ('dayvolume', 'avgdailyvol3m', 'intradaymarketcap')
        for sort_field in sort_fields:
            for offset in self._SCREEN_OFFSETS:
                try:
                    with YF_LOCK:
                        response = yf.screen(
                            query,
                            size=self._SCREEN_PAGE_SIZE,
                            offset=offset,
                            sortField=sort_field,
                            sortAsc=False,
                        )
                except Exception as exc:
                    logger.info('Overview trading-volume screen failed for %s offset %s: %s', sort_field, offset, exc)
                    continue
                if not isinstance(response, dict):
                    continue
                quotes = response.get('quotes') or []
                if not isinstance(quotes, list):
                    continue
                for quote in quotes:
                    if not isinstance(quote, dict):
                        continue
                    symbol = str(quote.get('symbol') or '').upper().strip()
                    if symbol and symbol not in by_symbol:
                        by_symbol[symbol] = dict(quote)
        return list(by_symbol.values())

    def _rows_from_quotes(self, quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for quote in quotes:
            quote_type = str(quote.get('quoteType') or '').upper().strip()
            if quote_type and quote_type != 'EQUITY':
                continue
            symbol = str(quote.get('symbol') or '').upper().strip()
            if not symbol:
                continue
            price = self._first_number(
                quote.get('regularMarketPrice'),
                quote.get('intradayprice'),
                quote.get('regularMarketPreviousClose'),
                quote.get('eodprice'),
            )
            volume = self._first_number(
                quote.get('regularMarketVolume'),
                quote.get('dayvolume'),
                quote.get('eodvolume'),
            )
            if price is None or volume is None or price <= 0 or volume <= 0:
                continue
            one_day_dollar_volume = price * volume
            market_cap = self._first_number(
                quote.get('marketCap'),
                quote.get('intradaymarketcap'),
                quote.get('lastclosemarketcap.lasttwelvemonths'),
            )
            avg_share_volume = self._first_number(
                quote.get('averageDailyVolume10Day'),
                quote.get('averageDailyVolume3Month'),
                quote.get('avgdailyvol3m'),
            )
            rows.append({
                'ticker': symbol,
                'name': str(quote.get('longName') or quote.get('shortName') or quote.get('displayName') or symbol),
                'sector': str(quote.get('sectorDisp') or quote.get('sector') or 'N/A'),
                'market_cap': market_cap,
                'one_day_dollar_volume': one_day_dollar_volume,
                'five_day_avg_dollar_volume': price * avg_share_volume if avg_share_volume else None,
                'thirty_day_avg_dollar_volume': None,
                'ytd_avg_dollar_volume': None,
                'one_year_avg_dollar_volume': None,
                '_avg_share_volume': avg_share_volume,
                '_price': price,
            })
        return rows

    def _merge_trading_volume_history(self, rows: list[dict[str, Any]]) -> None:
        symbols = [str(row.get('ticker') or '').strip() for row in rows if str(row.get('ticker') or '').strip()]
        if not symbols:
            return
        try:
            with YF_LOCK:
                history = yf.download(
                    tickers=symbols,
                    period='1y',
                    interval='1d',
                    group_by='ticker',
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                )
        except Exception as exc:
            logger.info('Overview trading-volume history fetch failed: %s', exc)
            return
        for row in rows:
            symbol = str(row.get('ticker') or '').strip()
            frame = self._history_frame_for_symbol(history, symbol, len(symbols))
            metrics = self._dollar_volume_metrics(frame)
            for key, value in metrics.items():
                if value is not None:
                    row[key] = value

    def _history_frame_for_symbol(self, history: Any, symbol: str, symbol_count: int) -> Any:
        if history is None or getattr(history, 'empty', True):
            return None
        try:
            columns = history.columns
        except Exception:
            return None
        try:
            if getattr(columns, 'nlevels', 1) > 1:
                if symbol in columns.get_level_values(0):
                    return history[symbol]
                if symbol in columns.get_level_values(1):
                    return history.xs(symbol, axis=1, level=1)
            if symbol_count == 1:
                return history
        except Exception:
            return None
        return None

    def _dollar_volume_metrics(self, frame: Any) -> dict[str, float | None]:
        metrics = {
            'five_day_avg_dollar_volume': None,
            'thirty_day_avg_dollar_volume': None,
            'ytd_avg_dollar_volume': None,
            'one_year_avg_dollar_volume': None,
        }
        if frame is None or getattr(frame, 'empty', True):
            return metrics
        try:
            close = pd.to_numeric(frame.get('Close'), errors='coerce')
            volume = pd.to_numeric(frame.get('Volume'), errors='coerce')
            dollar_volume = (close * volume).dropna()
            if getattr(dollar_volume, 'empty', True):
                return metrics
            dollar_volume.index = pd.DatetimeIndex(pd.to_datetime(dollar_volume.index, errors='coerce')).tz_localize(None)
            dollar_volume = dollar_volume[pd.notna(dollar_volume.index)]
            if getattr(dollar_volume, 'empty', True):
                return metrics
            ytd_start = pd.Timestamp(datetime.date.today().replace(month=1, day=1))
            one_year_start = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=365))
            metrics['five_day_avg_dollar_volume'] = self._mean_dollar_volume(dollar_volume.tail(5))
            metrics['thirty_day_avg_dollar_volume'] = self._mean_dollar_volume(dollar_volume.tail(30))
            metrics['ytd_avg_dollar_volume'] = self._mean_dollar_volume(dollar_volume[dollar_volume.index >= ytd_start])
            metrics['one_year_avg_dollar_volume'] = self._mean_dollar_volume(dollar_volume[dollar_volume.index >= one_year_start])
        except Exception:
            return metrics
        return metrics

    def _mean_dollar_volume(self, values: Any) -> float | None:
        if getattr(values, 'empty', True):
            return None
        try:
            value = float(values.mean())
        except Exception:
            return None
        return value if math.isfinite(value) and value > 0 else None

    def _first_number(self, *values: Any) -> float | None:
        for value in values:
            try:
                numeric = float(value)
            except Exception:
                continue
            if math.isfinite(numeric):
                return numeric
        return None
