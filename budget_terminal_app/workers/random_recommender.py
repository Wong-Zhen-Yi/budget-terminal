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
    _MAX_OPTION_EXPIRIES = 4
    _POOL_FETCH_SIZE = 80
    _CANDIDATE_LIMIT = 30
    _PATTERN_CANDIDATE_LIMIT = 120
    _PATTERN_HISTORY_PERIOD = '1y'
    _ROLL_TOP_COUNT = 12

    def __init__(
        self,
        exclude_symbols: Any = None,
        history_symbols: Any = None,
        target_symbol: Any = '',
        pattern_modes: Any = None,
    ) -> None:
        super().__init__()
        self.exclude_symbols = self._normalize_symbol_set(exclude_symbols)
        self.history_symbols = self._normalize_symbol_set(history_symbols)
        self.target_symbol = str(target_symbol or '').upper().strip()
        self.pattern_modes = self._normalize_pattern_modes(pattern_modes)

    def _normalize_symbol_set(self, values: Any) -> set[str]:
        if not isinstance(values, (list, tuple, set)):
            return set()
        return {str(value or '').upper().strip() for value in values if str(value or '').strip()}

    def _to_float(self, value: Any) -> float | None:
        try:
            numeric = float(value)
        except Exception:
            return None
        return numeric if math.isfinite(numeric) else None

    def _normalize_pattern_modes(self, values: Any) -> set[str]:
        if isinstance(values, str):
            raw_values = [values]
        elif isinstance(values, (list, tuple, set)):
            raw_values = list(values)
        else:
            raw_values = []
        allowed = {
            'breakout',
            'consolidation',
            'downtrend',
            'double_bottom',
            'bullish_flag',
            'bullish_rsi_divergence',
        }
        return {str(value or '').strip().casefold() for value in raw_values if str(value or '').strip().casefold() in allowed}

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

    def _screen_quotes(self, query: Any, total: int, *, offset: int = 0, size: int = 1, sort_field: str = 'ticker', sort_asc: bool = True) -> list[dict[str, Any]]:
        if total <= 0:
            return []
        offset = max(0, min(int(offset), max(total - 1, 0)))
        response = yf.screen(query, size=max(1, int(size)), offset=offset, sortField=sort_field, sortAsc=sort_asc)
        if not isinstance(response, dict):
            return []
        quotes = response.get('quotes') or []
        if not isinstance(quotes, list):
            return []
        return [dict(quote) for quote in quotes if isinstance(quote, dict)]

    def _screen_quote(self, query: Any, total: int) -> dict[str, Any]:
        quotes = self._screen_quotes(
            query,
            total,
            offset=random.randint(0, max(total - 1, 0)),
            size=1,
            sort_field='ticker',
            sort_asc=True,
        )
        return quotes[0] if quotes else {}

    def _fallback_quote_from_info(self, symbol: str, info: dict[str, Any]) -> dict[str, Any]:
        return {
            'symbol': symbol,
            'shortName': info.get('shortName') or info.get('longName') or symbol,
            'longName': info.get('longName') or info.get('shortName') or symbol,
            'regularMarketPrice': info.get('regularMarketPrice') or info.get('currentPrice'),
            'regularMarketPreviousClose': info.get('previousClose') or info.get('regularMarketPreviousClose'),
            'regularMarketChange': info.get('regularMarketChange'),
            'regularMarketChangePercent': info.get('regularMarketChangePercent'),
            'marketCap': info.get('marketCap'),
            'trailingPE': info.get('trailingPE'),
            'forwardPE': info.get('forwardPE'),
            'beta': info.get('beta'),
            'dividendYield': info.get('dividendYield'),
            'averageDailyVolume3Month': info.get('averageVolume'),
            'fiftyTwoWeekLow': info.get('fiftyTwoWeekLow'),
            'fiftyTwoWeekHigh': info.get('fiftyTwoWeekHigh'),
            'fiftyTwoWeekChangePercent': info.get('52WeekChange'),
            'exchange': info.get('exchange') or info.get('fullExchangeName'),
            'fullExchangeName': info.get('fullExchangeName') or info.get('exchange'),
            'currency': info.get('currency'),
            'quoteType': info.get('quoteType'),
        }

    def _build_candidate_pool(self, query: Any, total: int) -> list[dict[str, Any]]:
        offsets = {0}
        if total > self._POOL_FETCH_SIZE:
            max_offset = max(total - self._POOL_FETCH_SIZE, 0)
            offsets.update(random.randint(0, max_offset) for _ in range(3))
        requests = [
            ('intradaymarketcap', False, 0),
            ('avgdailyvol3m', False, 0),
            ('percentchange', False, 0),
            ('fiftytwowkpercentchange', False, 0),
        ]
        if self.pattern_modes.intersection({'downtrend', 'double_bottom', 'bullish_rsi_divergence'}):
            requests.extend([
                ('percentchange', True, 0),
                ('fiftytwowkpercentchange', True, 0),
            ])
        if self.pattern_modes.intersection({'bullish_flag', 'bullish_rsi_divergence'}):
            requests.extend([
                ('percentchange', False, 0),
                ('fiftytwowkpercentchange', False, 0),
            ])
        for offset in sorted(offsets):
            requests.append(('ticker', True, offset))

        by_symbol: dict[str, dict[str, Any]] = {}
        for sort_field, sort_asc, offset in requests:
            try:
                quotes = self._screen_quotes(
                    query,
                    total,
                    offset=offset,
                    size=self._POOL_FETCH_SIZE,
                    sort_field=sort_field,
                    sort_asc=sort_asc,
                )
            except Exception as exc:
                logger.info('Roll candidate screen failed for %s: %s', sort_field, exc)
                continue
            for quote in quotes:
                symbol = str(quote.get('symbol') or '').upper().strip()
                if not symbol or symbol in by_symbol:
                    continue
                if self._quote_is_screenable(quote):
                    by_symbol[symbol] = quote
        candidates = [self._candidate_from_quote(quote) for quote in by_symbol.values()]
        candidates = [candidate for candidate in candidates if candidate]
        candidates.sort(key=lambda item: item.get('score', 0.0), reverse=True)
        for index, candidate in enumerate(candidates, start=1):
            candidate['rank'] = index
        limit = self._PATTERN_CANDIDATE_LIMIT if self.pattern_modes else self._CANDIDATE_LIMIT
        return candidates[:limit]

    def _quote_is_screenable(self, quote: dict[str, Any]) -> bool:
        symbol = str(quote.get('symbol') or '').upper().strip()
        quote_type = str(quote.get('quoteType') or '').upper().strip()
        price = self._to_float(quote.get('regularMarketPrice') or quote.get('regularMarketPreviousClose'))
        market_cap = self._to_float(quote.get('marketCap'))
        avg_volume = self._to_float(quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'))
        name = quote.get('longName') or quote.get('shortName') or quote.get('displayName')
        return bool(
            symbol
            and quote_type in ('EQUITY', '')
            and name
            and price is not None
            and market_cap is not None
            and avg_volume is not None
        )

    def _candidate_from_quote(self, quote: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(quote.get('symbol') or '').upper().strip()
        if not symbol:
            return None
        score, reasons = self._score_quote(symbol, quote)
        return {
            'symbol': symbol,
            'name': str(quote.get('longName') or quote.get('shortName') or quote.get('displayName') or symbol),
            'sector': str(quote.get('sector') or quote.get('sectorDisp') or 'N/A'),
            'score': round(score, 1),
            'reasons': reasons,
            'day_change_pct': quote.get('regularMarketChangePercent'),
            'fifty_two_week_change_pct': quote.get('fiftyTwoWeekChangePercent'),
            'average_volume': quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'),
            'market_cap': quote.get('marketCap'),
            'quote': quote,
        }

    def _score_quote(self, symbol: str, quote: dict[str, Any]) -> tuple[float, list[str]]:
        score = 0.0
        reasons = []

        market_cap = self._to_float(quote.get('marketCap'))
        if market_cap is not None:
            if market_cap >= 200_000_000_000:
                score += 16
                reasons.append('mega cap')
            elif market_cap >= 10_000_000_000:
                score += 14
                reasons.append('large cap')
            elif market_cap >= 2_000_000_000:
                score += 11
                reasons.append('mid cap')
            else:
                score += 8

        avg_volume = self._to_float(quote.get('averageDailyVolume3Month') or quote.get('averageDailyVolume10Day'))
        if avg_volume is not None:
            if avg_volume >= 10_000_000:
                score += 18
                reasons.append('very liquid')
            elif avg_volume >= 3_000_000:
                score += 15
                reasons.append('liquid')
            else:
                score += 10

        day_change = self._to_float(quote.get('regularMarketChangePercent'))
        if day_change is not None:
            if day_change >= 3:
                score += 9
                reasons.append('strong day move')
            elif day_change > 0:
                score += 7
                reasons.append('green today')
            elif day_change > -2:
                score += 4
            else:
                score += 1

        year_change = self._to_float(quote.get('fiftyTwoWeekChangePercent'))
        if year_change is not None:
            if year_change >= 40:
                score += 15
                reasons.append('strong 1Y momentum')
            elif year_change >= 10:
                score += 12
                reasons.append('positive 1Y trend')
            elif year_change >= 0:
                score += 8
            elif year_change > -20:
                score += 4

        analyst_rating = str(quote.get('averageAnalystRating') or '').strip()
        if analyst_rating:
            score += 10
            reasons.append(analyst_rating.split(' - ')[-1].lower())
        elif quote.get('epsForward') not in (None, '', 'N/A') or quote.get('forwardPE') not in (None, '', 'N/A'):
            score += 5

        metadata_fields = (
            'longName',
            'shortName',
            'fullExchangeName',
            'currency',
            'trailingPE',
            'forwardPE',
            'fiftyTwoWeekHigh',
            'fiftyTwoWeekLow',
        )
        metadata_count = sum(1 for field in metadata_fields if quote.get(field) not in (None, '', 'N/A'))
        score += min(14, metadata_count * 1.75)
        if metadata_count >= 6:
            reasons.append('complete quote')

        if symbol in self.exclude_symbols:
            score -= 14
        elif symbol in self.history_symbols:
            score -= 7
        else:
            score += 8
            reasons.append('fresh idea')

        return max(0.0, min(100.0, score)), reasons[:4]

    def _select_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            return {}
        if self.target_symbol:
            target = next((candidate for candidate in candidates if candidate.get('symbol') == self.target_symbol), None)
            if target:
                return target
        fresh_candidates = [candidate for candidate in candidates if candidate.get('symbol') not in self.exclude_symbols and candidate.get('symbol') not in self.history_symbols]
        choice_pool = fresh_candidates or [candidate for candidate in candidates if candidate.get('symbol') not in self.exclude_symbols] or candidates
        top_pool = choice_pool[:self._ROLL_TOP_COUNT]
        if len(top_pool) <= 1:
            return top_pool[0]
        if self.pattern_modes:
            weights = [
                max(1.0, float(candidate.get('pattern_score', 0.0) or 0.0) + float(candidate.get('score', 0.0) or 0.0) * 0.25)
                for candidate in top_pool
            ]
        else:
            weights = [max(1.0, float(candidate.get('score', 0.0) or 0.0)) for candidate in top_pool]
        try:
            return random.choices(top_pool, weights=weights, k=1)[0]
        except Exception:
            return random.choice(top_pool)

    def _candidate_for_target(self, symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
        candidate = self._candidate_from_quote(quote)
        if candidate is None:
            candidate = {
                'symbol': symbol,
                'name': str(quote.get('longName') or quote.get('shortName') or symbol),
                'sector': 'N/A',
                'score': 0.0,
                'reasons': ['selected candidate'],
                'quote': quote,
            }
        candidate.setdefault('rank', 0)
        return candidate

    def _candidate_reason_text(self, candidate: dict[str, Any]) -> str:
        reasons = [str(reason or '').strip() for reason in list(candidate.get('reasons') or []) if str(reason or '').strip()]
        return ', '.join(reasons) if reasons else 'scored candidate'

    def _download_pattern_history(self, symbols: list[str]) -> Any:
        if not symbols:
            return None
        try:
            return yf.download(
                symbols,
                period=self._PATTERN_HISTORY_PERIOD,
                interval='1d',
                group_by='ticker',
                progress=False,
                auto_adjust=False,
                threads=True,
            )
        except Exception as exc:
            logger.info('Roll pattern history batch failed: %s', exc)
            return None

    def _symbol_history_from_batch(self, batch_data: Any, symbols: list[str], symbol: str) -> Any:
        if batch_data is None or getattr(batch_data, 'empty', True):
            return None
        try:
            if isinstance(batch_data.columns, pd.MultiIndex):
                level_zero = batch_data.columns.get_level_values(0)
                level_one = batch_data.columns.get_level_values(1)
                if symbol in level_zero:
                    return batch_data[symbol].dropna(how='all')
                if symbol in level_one:
                    return batch_data.xs(symbol, axis=1, level=1).dropna(how='all')
                return None
            if len(symbols) == 1:
                return batch_data.dropna(how='all')
        except Exception:
            return None
        return None

    def _load_pattern_history(self, symbol: str, batch_data: Any, symbols: list[str]) -> Any:
        frame = self._symbol_history_from_batch(batch_data, symbols, symbol)
        if frame is None or getattr(frame, 'empty', True):
            try:
                frame = yf.Ticker(symbol).history(period=self._PATTERN_HISTORY_PERIOD, interval='1d', auto_adjust=False)
            except Exception as exc:
                logger.info('Roll pattern history failed for %s: %s', symbol, exc)
                return None
        if frame is None or getattr(frame, 'empty', True):
            return None
        required = {'High', 'Low', 'Close', 'Volume'}
        if not required.issubset(set(frame.columns)):
            return None
        return frame[list(required)].dropna(how='any')

    def _pattern_snapshot_value(self, value: Any, decimals: int = 2) -> Any:
        numeric = self._to_float(value)
        if numeric is None:
            return None
        return round(numeric, decimals)

    def _latest_series_value(self, series: Any, offset: int = 0) -> float | None:
        try:
            clean = series.dropna()
        except Exception:
            return None
        if clean.empty or len(clean) <= offset:
            return None
        return self._to_float(clean.iloc[-1 - offset])

    def _series_change(self, series: Any, periods: int) -> float | None:
        current = self._latest_series_value(series)
        prior = self._latest_series_value(series, periods)
        if current is None or prior is None:
            return None
        return current - prior

    def _calculate_rsi(self, close: Any, period: int = 14) -> Any:
        delta = close.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.where(avg_loss != 0)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.where(avg_loss != 0, 100.0)
        rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
        return rsi.fillna(50.0).clip(lower=0, upper=100)

    def _calculate_macd(self, close: Any) -> tuple[Any, Any, Any]:
        ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
        histogram = macd_line - signal
        return macd_line, signal, histogram

    def _evaluate_breakout_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 70:
            return False, 0.0, [], {}
        high = pd.to_numeric(frame['High'], errors='coerce')
        low = pd.to_numeric(frame['Low'], errors='coerce')
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        resistance_window = high.iloc[:-5].tail(55) if len(high) > 60 else high.shift(1).tail(55)
        prior_high = self._to_float(resistance_window.max())
        sma20_series = close.rolling(20, min_periods=20).mean()
        sma50_series = close.rolling(50, min_periods=50).mean()
        sma200_series = close.rolling(200, min_periods=180).mean()
        ema8_series = close.ewm(span=8, adjust=False, min_periods=8).mean()
        ema21_series = close.ewm(span=21, adjust=False, min_periods=21).mean()
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema8 = self._latest_series_value(ema8_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = volume.rolling(20, min_periods=10).mean()
        vol50_series = volume.rolling(50, min_periods=20).mean()
        vol120_series = volume.rolling(120, min_periods=60).mean()
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)
        rsi_series = self._calculate_rsi(close)
        rsi_ma_series = rsi_series.rolling(10, min_periods=5).mean()
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        macd_line_series, macd_signal_series, macd_hist_series = self._calculate_macd(close)
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        if None in (last_close, prior_high, sma20, sma50, ema21) or not prior_high:
            return False, 0.0, [], {}

        distance_to_resistance = (last_close - prior_high) / prior_high
        recent_closes = close.tail(10)
        breakout_closes_5 = int((close.tail(5) > prior_high * 1.002).sum())
        breakout_closes_10 = int((recent_closes > prior_high * 1.002).sum())
        recent_high = self._to_float(high.tail(10).max())
        pre_breakout = -0.05 <= distance_to_resistance <= 0.002
        fresh_breakout = 0.002 < distance_to_resistance <= 0.012 and breakout_closes_5 <= 2 and breakout_closes_10 <= 4
        late_breakout = distance_to_resistance > 0.012 or breakout_closes_5 > 2 or breakout_closes_10 > 4

        above_daily_support = last_close >= min(sma20, ema21) * 0.995
        ma_stack_aligned = sma20 >= sma50 * 0.98
        if sma200 is not None:
            ma_stack_aligned = ma_stack_aligned and sma50 >= sma200 * 0.97
        fast_ma_aligned = ema8 is not None and ema8 >= ema21 * 0.995
        distance_to_sma20 = (last_close - sma20) / sma20 if sma20 else 1.0
        distance_to_ema21 = (last_close - ema21) / ema21 if ema21 else 1.0
        not_overextended = (
            distance_to_sma20 <= 0.06
            and distance_to_ema21 <= 0.08
            and (recent_high is None or recent_high <= prior_high * 1.05)
        )

        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_ma_change_10 = self._series_change(rsi_ma_series, 10)
        rsi_change_30 = self._series_change(rsi_series, 30)
        rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
        rsi_healthy = rsi is not None and 45 <= rsi <= 74
        rsi_short_ok = rsi_above_ma and (rsi_change_5 is None or rsi_change_5 >= -1.5)
        rsi_intermediate_ok = rsi is not None and rsi >= 50 and (rsi_ma_change_10 is None or rsi_ma_change_10 >= -1.0)
        rsi_long_ok = rsi is not None and rsi >= 45 and (rsi_change_30 is None or rsi_change_30 >= -6.0)
        rsi_ok = bool(rsi_above_ma and rsi_healthy and (rsi_short_ok or rsi_intermediate_ok))

        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)
        macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
        macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 > 0)
        macd_short_ok = bool(macd_turning_up and (macd_hist is None or macd_hist > -abs(last_close) * 0.004))
        macd_intermediate_ok = bool(macd_above_signal or (macd_hist is not None and macd_hist > 0))
        macd_long_ok = bool(macd_line is not None and (macd_line >= 0 or (macd_line_change_20 is not None and macd_line_change_20 > 0)))
        macd_ok = bool(macd_short_ok and (macd_intermediate_ok or macd_long_ok))

        volume_ok = True
        if vol20 is not None and vol50 is not None and vol50 > 0:
            volume_ok = vol20 >= vol50 * 0.85
        if latest_volume is not None and vol20 is not None and vol20 > 0:
            volume_ok = volume_ok or latest_volume >= vol20 * 0.9
            volume_ok = volume_ok and latest_volume <= vol20 * 2.8
        volume_short_ok = bool(latest_volume is None or vol20 is None or latest_volume >= vol20 * 0.75)
        volume_intermediate_ok = bool(vol20 is None or vol50 is None or vol50 <= 0 or vol20 >= vol50 * 0.85)
        volume_long_ok = bool(vol50 is None or vol120 is None or vol120 <= 0 or vol50 >= vol120 * 0.75)
        volume_accumulation = bool(
            (vol20 is not None and vol50 is not None and vol50 > 0 and vol20 >= vol50 * 0.95)
            or (latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume >= vol20 * 1.05)
        )

        short_timeframe_ok = bool((rsi_short_ok or macd_short_ok) and volume_short_ok)
        intermediate_timeframe_ok = bool((rsi_intermediate_ok or macd_intermediate_ok) and volume_intermediate_ok)
        long_timeframe_ok = bool((rsi_long_ok or macd_long_ok) and volume_long_ok)
        timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
        indicator_confirmations = sum(1 for value in (rsi_ok, macd_ok, volume_ok, timeframe_agreement_count >= 2) if value)

        timing_ok = pre_breakout or fresh_breakout
        if pre_breakout:
            setup_stage = 'Pre-Breakout'
        elif fresh_breakout:
            setup_stage = 'Fresh Breakout'
        else:
            setup_stage = 'Late Breakout' if late_breakout else 'No Breakout'

        score = 0.0
        reasons = []
        if pre_breakout:
            score += 28
            reasons.append('near resistance' if distance_to_resistance >= -0.02 else 'coiling below resistance')
        elif fresh_breakout:
            score += 20
            reasons.append('fresh breakout')
        if breakout_closes_5 <= 2 and breakout_closes_10 <= 4:
            score += 6
            reasons.append('few breakout closes')
        if above_daily_support:
            score += 8
            reasons.append('above daily support')
        if ma_stack_aligned and fast_ma_aligned:
            score += 14
            reasons.append('daily MA stack aligned')
        elif ma_stack_aligned or fast_ma_aligned:
            score += 8
            reasons.append('daily MAs improving')
        if not_overextended:
            score += 10
            reasons.append('not overextended')
        if rsi_above_ma:
            score += 8
            reasons.append('RSI above RSI MA')
        if rsi_healthy:
            score += 5
            reasons.append('RSI constructive')
        if macd_turning_up:
            score += 8
            reasons.append('MACD turning up')
        if macd_above_signal:
            score += 5
            reasons.append('MACD above signal')
        if volume_accumulation:
            score += 8
            reasons.append('volume accumulation')
        if volume_ok:
            score += 4
            reasons.append('volume controlled')
        if timeframe_agreement_count >= 2:
            score += 10
            reasons.append('multi-timeframe confirmation')
        elif timeframe_agreement_count == 1:
            score += 4

        if late_breakout:
            score -= 18
        if not not_overextended:
            score -= 12
        if rsi is not None and rsi > 76:
            score -= 8
        if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 2.8:
            score -= 10

        snapshot = {
            'close': self._pattern_snapshot_value(last_close),
            'setup_stage': setup_stage,
            'resistance_55d': self._pattern_snapshot_value(prior_high),
            'distance_to_resistance_pct': self._pattern_snapshot_value(distance_to_resistance * 100.0),
            'breakout_closes_5d': breakout_closes_5,
            'breakout_closes_10d': breakout_closes_10,
            'sma20': self._pattern_snapshot_value(sma20),
            'sma50': self._pattern_snapshot_value(sma50),
            'sma200': self._pattern_snapshot_value(sma200),
            'ema8': self._pattern_snapshot_value(ema8),
            'ema21': self._pattern_snapshot_value(ema21),
            'distance_to_sma20_pct': self._pattern_snapshot_value(distance_to_sma20 * 100.0),
            'daily_ma_stack': 'aligned' if ma_stack_aligned and fast_ma_aligned else ('improving' if ma_stack_aligned or fast_ma_aligned else 'mixed'),
            'rsi14': self._pattern_snapshot_value(rsi),
            'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
            'rsi_state': 'above RSI MA' if rsi_above_ma else 'below RSI MA',
            'macd_line': self._pattern_snapshot_value(macd_line),
            'macd_signal': self._pattern_snapshot_value(macd_signal),
            'macd_histogram': self._pattern_snapshot_value(macd_hist),
            'macd_state': 'turning up' if macd_turning_up else ('above signal' if macd_above_signal else 'mixed'),
            'volume20': self._pattern_snapshot_value(vol20, 0),
            'volume50': self._pattern_snapshot_value(vol50, 0),
            'volume120': self._pattern_snapshot_value(vol120, 0),
            'volume_state': 'accumulation' if volume_accumulation else ('controlled' if volume_ok else 'weak or disorderly'),
            'short_timeframe_confirmed': short_timeframe_ok,
            'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
            'long_timeframe_confirmed': long_timeframe_ok,
            'timeframe_agreement': f'{timeframe_agreement_count}/3',
        }
        matched = bool(
            timing_ok
            and not late_breakout
            and above_daily_support
            and not_overextended
            and indicator_confirmations >= 2
            and timeframe_agreement_count >= 2
            and score >= 58
        )
        return matched, max(0.0, min(100.0, score)), reasons[:8], snapshot

    def _evaluate_downtrend_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 70:
            return False, 0.0, [], {}
        high = pd.to_numeric(frame['High'], errors='coerce')
        low = pd.to_numeric(frame['Low'], errors='coerce')
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        sma20_series = close.rolling(20, min_periods=20).mean()
        sma50_series = close.rolling(50, min_periods=50).mean()
        sma200_series = close.rolling(200, min_periods=180).mean()
        ema8_series = close.ewm(span=8, adjust=False, min_periods=8).mean()
        ema21_series = close.ewm(span=21, adjust=False, min_periods=21).mean()
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema8 = self._latest_series_value(ema8_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = volume.rolling(20, min_periods=10).mean()
        vol50_series = volume.rolling(50, min_periods=20).mean()
        vol120_series = volume.rolling(120, min_periods=60).mean()
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)
        if None in (last_close, sma20, sma50, ema21) or not last_close:
            return False, 0.0, [], {}

        rsi_series = self._calculate_rsi(close)
        rsi_ma_series = rsi_series.rolling(10, min_periods=5).mean()
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_ma_change_10 = self._series_change(rsi_ma_series, 10)
        rsi_change_30 = self._series_change(rsi_series, 30)
        macd_line_series, macd_signal_series, macd_hist_series = self._calculate_macd(close)
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        prior_20_close = self._latest_series_value(close, 20)
        prior_60_close = self._latest_series_value(close, 60)
        decline_20 = (last_close - prior_20_close) / prior_20_close if prior_20_close else 0.0
        decline_60 = (last_close - prior_60_close) / prior_60_close if prior_60_close else 0.0
        recent_20_high = self._to_float(high.tail(20).max())
        previous_20_high = self._to_float(high.iloc[-40:-20].max()) if len(high) >= 40 else None
        recent_20_low = self._to_float(low.tail(20).min())
        previous_20_low = self._to_float(low.iloc[-40:-20].min()) if len(low) >= 40 else None
        lower_highs = previous_20_high is not None and recent_20_high is not None and recent_20_high <= previous_20_high * 0.995
        lower_lows = previous_20_low is not None and recent_20_low is not None and recent_20_low <= previous_20_low * 1.01
        below_daily_mas = last_close <= min(sma20, ema21) * 1.01 and last_close <= sma50 * 1.02
        bearish_stack = sma20 <= sma50 * 1.02 and (ema8 is None or ema8 <= ema21 * 1.01)
        if sma200 is not None:
            bearish_stack = bearish_stack and sma50 <= sma200 * 1.03
        distance_to_sma20 = (last_close - sma20) / sma20 if sma20 else 0.0
        distance_to_sma50 = (last_close - sma50) / sma50 if sma50 else 0.0
        controlled_decline = distance_to_sma20 >= -0.18 and (rsi is None or rsi >= 24)

        rsi_below_ma = rsi is not None and rsi_ma is not None and rsi <= rsi_ma
        rsi_bearish = rsi is not None and 26 <= rsi <= 52
        rsi_short_ok = bool(rsi_below_ma and (rsi_change_5 is None or rsi_change_5 <= 2.0))
        rsi_intermediate_ok = bool(rsi is not None and rsi <= 50 and (rsi_ma_change_10 is None or rsi_ma_change_10 <= 1.0))
        rsi_long_ok = bool(rsi is not None and rsi <= 55 and (rsi_change_30 is None or rsi_change_30 <= 6.0))
        rsi_ok = bool(rsi_below_ma and rsi_bearish and (rsi_short_ok or rsi_intermediate_ok))

        macd_below_signal = macd_line is not None and macd_signal is not None and macd_line <= macd_signal
        macd_negative = macd_line is not None and macd_line <= 0
        macd_weakening = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 < 0)
        macd_short_ok = bool(macd_below_signal or macd_weakening)
        macd_intermediate_ok = bool(macd_negative or (macd_hist is not None and macd_hist < 0))
        macd_long_ok = bool(macd_line is not None and (macd_line <= 0 or (macd_line_change_20 is not None and macd_line_change_20 < 0)))
        macd_ok = bool(macd_short_ok and (macd_intermediate_ok or macd_long_ok))

        recent_frame = frame.tail(20).copy()
        down_volume_avg = None
        up_volume_avg = None
        try:
            recent_close = pd.to_numeric(recent_frame['Close'], errors='coerce')
            recent_open = pd.to_numeric(recent_frame['Open'], errors='coerce') if 'Open' in recent_frame.columns else recent_close.shift(1)
            recent_volume = pd.to_numeric(recent_frame['Volume'], errors='coerce')
            down_volume_avg = self._to_float(recent_volume[recent_close < recent_open].mean())
            up_volume_avg = self._to_float(recent_volume[recent_close >= recent_open].mean())
        except Exception:
            pass
        downside_volume = bool(
            (down_volume_avg is not None and up_volume_avg is not None and up_volume_avg > 0 and down_volume_avg >= up_volume_avg * 0.9)
            or (latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume >= vol20 * 0.85)
        )
        volume_controlled = True
        if latest_volume is not None and vol20 is not None and vol20 > 0:
            volume_controlled = latest_volume <= vol20 * 3.2
        volume_short_ok = bool(downside_volume or latest_volume is None or vol20 is None or latest_volume >= vol20 * 0.75)
        volume_intermediate_ok = bool(vol20 is None or vol50 is None or vol50 <= 0 or vol20 >= vol50 * 0.75)
        volume_long_ok = bool(vol50 is None or vol120 is None or vol120 <= 0 or vol50 >= vol120 * 0.65)

        price_short_ok = bool(last_close <= sma20 * 1.01 or decline_20 <= -0.02)
        price_intermediate_ok = bool(last_close <= sma50 * 1.02 or decline_60 <= -0.04)
        price_long_ok = bool(sma200 is None or last_close <= sma200 * 1.03 or decline_60 <= -0.06)
        short_timeframe_ok = bool((price_short_ok or rsi_short_ok or macd_short_ok) and volume_short_ok)
        intermediate_timeframe_ok = bool((price_intermediate_ok or rsi_intermediate_ok or macd_intermediate_ok) and volume_intermediate_ok)
        long_timeframe_ok = bool((price_long_ok or rsi_long_ok or macd_long_ok) and volume_long_ok)
        timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
        indicator_confirmations = sum(1 for value in (rsi_ok, macd_ok, downside_volume, timeframe_agreement_count >= 2) if value)

        score = 0.0
        reasons = []
        if below_daily_mas:
            score += 18
            reasons.append('below daily MAs')
        if bearish_stack:
            score += 16
            reasons.append('bearish MA stack')
        if lower_highs:
            score += 12
            reasons.append('lower highs')
        if lower_lows:
            score += 10
            reasons.append('lower lows')
        if decline_20 <= -0.03 or decline_60 <= -0.06:
            score += 10
            reasons.append('negative price trend')
        if rsi_below_ma:
            score += 8
            reasons.append('RSI below RSI MA')
        if rsi_bearish:
            score += 6
            reasons.append('RSI bearish')
        if macd_below_signal:
            score += 8
            reasons.append('MACD below signal')
        if macd_negative or macd_weakening:
            score += 6
            reasons.append('MACD weakening')
        if downside_volume:
            score += 8
            reasons.append('downside volume')
        if volume_controlled:
            score += 4
            reasons.append('volume controlled')
        if timeframe_agreement_count >= 2:
            score += 10
            reasons.append('multi-timeframe downtrend')
        elif timeframe_agreement_count == 1:
            score += 4
        if not controlled_decline:
            score -= 12
        if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 3.2:
            score -= 8

        snapshot = {
            'close': self._pattern_snapshot_value(last_close),
            'setup_stage': 'Downtrend',
            'decline_20d_pct': self._pattern_snapshot_value(decline_20 * 100.0),
            'decline_60d_pct': self._pattern_snapshot_value(decline_60 * 100.0),
            'distance_to_sma20_pct': self._pattern_snapshot_value(distance_to_sma20 * 100.0),
            'distance_to_sma50_pct': self._pattern_snapshot_value(distance_to_sma50 * 100.0),
            'sma20': self._pattern_snapshot_value(sma20),
            'sma50': self._pattern_snapshot_value(sma50),
            'sma200': self._pattern_snapshot_value(sma200),
            'ema8': self._pattern_snapshot_value(ema8),
            'ema21': self._pattern_snapshot_value(ema21),
            'daily_ma_stack': 'bearish' if bearish_stack else ('below MAs' if below_daily_mas else 'mixed'),
            'lower_highs': lower_highs,
            'lower_lows': lower_lows,
            'rsi14': self._pattern_snapshot_value(rsi),
            'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
            'rsi_state': 'below RSI MA' if rsi_below_ma else 'above RSI MA',
            'macd_line': self._pattern_snapshot_value(macd_line),
            'macd_signal': self._pattern_snapshot_value(macd_signal),
            'macd_histogram': self._pattern_snapshot_value(macd_hist),
            'macd_state': 'below signal' if macd_below_signal else ('weakening' if macd_weakening else 'mixed'),
            'volume20': self._pattern_snapshot_value(vol20, 0),
            'volume50': self._pattern_snapshot_value(vol50, 0),
            'volume120': self._pattern_snapshot_value(vol120, 0),
            'volume_state': 'downside participation' if downside_volume else ('controlled' if volume_controlled else 'disorderly'),
            'short_timeframe_confirmed': short_timeframe_ok,
            'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
            'long_timeframe_confirmed': long_timeframe_ok,
            'timeframe_agreement': f'{timeframe_agreement_count}/3',
        }
        matched = bool(
            below_daily_mas
            and (bearish_stack or lower_highs or lower_lows)
            and controlled_decline
            and indicator_confirmations >= 2
            and timeframe_agreement_count >= 2
            and score >= 58
        )
        return matched, max(0.0, min(100.0, score)), reasons[:8], snapshot

    def _evaluate_consolidation_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 70:
            return False, 0.0, [], {}
        high = pd.to_numeric(frame['High'], errors='coerce')
        low = pd.to_numeric(frame['Low'], errors='coerce')
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        range_high = self._to_float(high.tail(20).max())
        range_low = self._to_float(low.tail(20).min())
        prev_close = close.shift(1)
        true_range = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr20 = self._to_float(true_range.rolling(20, min_periods=15).mean().iloc[-1])
        atr60 = self._to_float(true_range.rolling(60, min_periods=40).mean().iloc[-1])
        vol20 = self._to_float(volume.rolling(20, min_periods=10).mean().iloc[-1])
        vol60 = self._to_float(volume.rolling(60, min_periods=30).mean().iloc[-1])
        if None in (last_close, range_high, range_low, atr20, atr60) or not last_close or not atr60:
            return False, 0.0, [], {}

        range_pct = (range_high - range_low) / last_close if last_close else 1.0
        atr_contracting = atr20 <= atr60 * 0.85
        tight_range = range_pct <= 0.14
        inside_range = range_low * 1.01 <= last_close <= range_high * 0.99
        orderly_volume = True
        if vol20 is not None and vol60 is not None and vol60 > 0:
            orderly_volume = vol20 <= vol60 * 1.25

        score = 0.0
        reasons = []
        if tight_range:
            score += 35
            reasons.append('tight 20D range')
        if atr_contracting:
            score += 30
            reasons.append('volatility contracted')
        if inside_range:
            score += 20
            reasons.append('inside range')
        if orderly_volume:
            score += 15
            reasons.append('orderly volume')

        snapshot = {
            'close': self._pattern_snapshot_value(last_close),
            'range_20d_high': self._pattern_snapshot_value(range_high),
            'range_20d_low': self._pattern_snapshot_value(range_low),
            'range_pct': self._pattern_snapshot_value(range_pct * 100.0),
            'atr20': self._pattern_snapshot_value(atr20),
            'atr60': self._pattern_snapshot_value(atr60),
            'volume20': self._pattern_snapshot_value(vol20, 0),
            'volume60': self._pattern_snapshot_value(vol60, 0),
        }
        return bool(tight_range and atr_contracting and inside_range and orderly_volume), min(100.0, score), reasons, snapshot

    def _evaluate_double_bottom_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 90:
            return False, 0.0, [], {}
        high = pd.to_numeric(frame['High'], errors='coerce')
        low = pd.to_numeric(frame['Low'], errors='coerce')
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        if last_close is None or last_close <= 0:
            return False, 0.0, [], {}

        sma20_series = close.rolling(20, min_periods=20).mean()
        sma50_series = close.rolling(50, min_periods=50).mean()
        sma200_series = close.rolling(200, min_periods=180).mean()
        ema21_series = close.ewm(span=21, adjust=False, min_periods=21).mean()
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = volume.rolling(20, min_periods=10).mean()
        vol50_series = volume.rolling(50, min_periods=20).mean()
        vol120_series = volume.rolling(120, min_periods=60).mean()
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)

        rsi_series = self._calculate_rsi(close)
        rsi_ma_series = rsi_series.rolling(10, min_periods=5).mean()
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_change_20 = self._series_change(rsi_series, 20)
        macd_line_series, macd_signal_series, macd_hist_series = self._calculate_macd(close)
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        lookback_start = max(0, len(low) - 120)
        swing_lows = []
        for index in range(max(3, lookback_start), max(3, len(low) - 3)):
            low_value = self._to_float(low.iloc[index])
            if low_value is None or low_value <= 0:
                continue
            window = low.iloc[max(0, index - 3):min(len(low), index + 4)].dropna()
            if len(window) < 5:
                continue
            window_min = self._to_float(window.min())
            if window_min is not None and low_value <= window_min * 1.003:
                swing_lows.append(index)

        best_score = 0.0
        best_reasons: list[str] = []
        best_snapshot: dict[str, Any] = {}
        best_matched = False
        for first_index in swing_lows:
            for second_index in swing_lows:
                if second_index <= first_index:
                    continue
                separation = second_index - first_index
                days_since_second = len(low) - 1 - second_index
                if separation < 15 or separation > 80 or days_since_second < 3 or days_since_second > 45:
                    continue
                first_bottom = self._to_float(low.iloc[first_index])
                second_bottom = self._to_float(low.iloc[second_index])
                if first_bottom is None or second_bottom is None or first_bottom <= 0 or second_bottom <= 0:
                    continue
                average_bottom = (first_bottom + second_bottom) / 2.0
                bottom_gap = abs(first_bottom - second_bottom) / average_bottom if average_bottom else 1.0
                if bottom_gap > 0.05:
                    continue
                neckline = self._to_float(high.iloc[first_index:second_index + 1].max())
                if neckline is None or neckline <= 0:
                    continue
                neckline_height = (neckline - average_bottom) / average_bottom if average_bottom else 0.0
                if neckline_height < 0.06:
                    continue
                post_second_low = self._to_float(low.iloc[second_index + 1:].min()) if second_index + 1 < len(low) else None
                if post_second_low is not None and post_second_low < min(first_bottom, second_bottom) * 0.985:
                    continue

                prior_high = self._to_float(high.iloc[max(0, first_index - 45):first_index].max()) if first_index > 0 else None
                first_close = self._to_float(close.iloc[first_index])
                prior_close = self._to_float(close.iloc[first_index - 30]) if first_index >= 30 else None
                prior_decline = None
                prior_weakness = False
                if prior_high is not None and prior_high > 0:
                    prior_decline = (average_bottom - prior_high) / prior_high
                    prior_weakness = prior_decline <= -0.08
                if not prior_weakness and prior_close is not None and prior_close > 0 and first_close is not None:
                    prior_decline = (first_close - prior_close) / prior_close
                    prior_weakness = prior_decline <= -0.06
                if not prior_weakness:
                    continue

                distance_to_neckline = (last_close - neckline) / neckline
                rebound_from_second = (last_close - second_bottom) / second_bottom
                if distance_to_neckline < -0.08 or distance_to_neckline > 0.06 or rebound_from_second < 0.04:
                    continue

                recent_frame = frame.iloc[second_index:].copy()
                up_volume_avg = None
                down_volume_avg = None
                try:
                    recent_close = pd.to_numeric(recent_frame['Close'], errors='coerce')
                    recent_open = pd.to_numeric(recent_frame['Open'], errors='coerce') if 'Open' in recent_frame.columns else recent_close.shift(1)
                    recent_volume = pd.to_numeric(recent_frame['Volume'], errors='coerce')
                    up_volume_avg = self._to_float(recent_volume[recent_close >= recent_open].mean())
                    down_volume_avg = self._to_float(recent_volume[recent_close < recent_open].mean())
                except Exception:
                    pass
                constructive_volume = bool(
                    (up_volume_avg is not None and down_volume_avg is not None and down_volume_avg > 0 and up_volume_avg >= down_volume_avg * 0.9)
                    or (latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume >= vol20 * 0.85)
                )
                volume_controlled = True
                if latest_volume is not None and vol20 is not None and vol20 > 0:
                    volume_controlled = latest_volume <= vol20 * 3.0
                volume_short_ok = bool(latest_volume is None or vol20 is None or latest_volume >= vol20 * 0.65)
                volume_intermediate_ok = bool(vol20 is None or vol50 is None or vol50 <= 0 or vol20 >= vol50 * 0.70)
                volume_long_ok = bool(vol50 is None or vol120 is None or vol120 <= 0 or vol50 >= vol120 * 0.60)
                volume_ok = bool(volume_controlled and (constructive_volume or volume_intermediate_ok))

                rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
                rsi_recovering = bool(
                    rsi is not None
                    and 38 <= rsi <= 70
                    and (
                        rsi_above_ma
                        or (rsi_change_5 is not None and rsi_change_5 >= 0)
                        or (rsi_change_20 is not None and rsi_change_20 >= 4)
                    )
                )
                rsi_short_ok = bool(rsi_above_ma or (rsi_change_5 is not None and rsi_change_5 >= -1.0))
                rsi_intermediate_ok = bool(rsi is not None and rsi >= 42 and (rsi_change_20 is None or rsi_change_20 >= -2.0))
                rsi_long_ok = bool(rsi is not None and rsi >= 38)

                macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
                macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 > 0)
                macd_recovering = macd_line_change_20 is not None and macd_line_change_20 > 0
                macd_ok = bool((macd_above_signal or macd_turning_up) and (macd_recovering or macd_hist is None or macd_hist > -abs(last_close) * 0.004))
                macd_short_ok = bool(macd_above_signal or macd_turning_up)
                macd_intermediate_ok = bool(macd_recovering or (macd_hist is not None and macd_hist >= 0))
                macd_long_ok = bool(macd_line is None or macd_line_change_20 is None or macd_line_change_20 >= -abs(last_close) * 0.002)

                price_short_ok = bool(rebound_from_second >= 0.06 and distance_to_neckline >= -0.08)
                price_intermediate_ok = bool(distance_to_neckline >= -0.06 or (sma20 is not None and last_close >= sma20 * 0.97))
                price_long_ok = bool(sma50 is None or last_close >= sma50 * 0.90 or distance_to_neckline >= -0.04)
                short_timeframe_ok = bool(price_short_ok and (rsi_short_ok or macd_short_ok or volume_short_ok))
                intermediate_timeframe_ok = bool(price_intermediate_ok and (rsi_intermediate_ok or macd_intermediate_ok or volume_intermediate_ok))
                long_timeframe_ok = bool(price_long_ok and (rsi_long_ok or macd_long_ok or volume_long_ok))
                timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
                indicator_confirmations = sum(1 for value in (rsi_recovering, macd_ok, volume_ok, timeframe_agreement_count >= 2) if value)

                neckline_breakout = last_close >= neckline * 1.002
                setup_stage = 'Double Bottom Breakout' if neckline_breakout else 'Double Bottom Rebound'
                score = 0.0
                reasons = []
                if bottom_gap <= 0.03:
                    score += 18
                    reasons.append('similar bottoms')
                else:
                    score += 12
                    reasons.append('bottoms within 5%')
                if neckline_height >= 0.10:
                    score += 18
                    reasons.append('clear neckline')
                else:
                    score += 12
                    reasons.append('meaningful neckline')
                if neckline_breakout:
                    score += 20
                    reasons.append('neckline breakout')
                else:
                    score += 16
                    reasons.append('rebounding toward neckline')
                if rebound_from_second >= 0.08:
                    score += 8
                    reasons.append('strong second-bottom rebound')
                else:
                    score += 4
                    reasons.append('second-bottom rebound')
                if prior_weakness:
                    score += 10
                    reasons.append('prior downtrend')
                if days_since_second <= 25:
                    score += 8
                    reasons.append('recent second bottom')
                else:
                    score += 4
                if rsi_recovering:
                    score += 10
                    reasons.append('RSI recovering')
                elif rsi is not None and rsi >= 38:
                    score += 4
                if macd_ok:
                    score += 10
                    reasons.append('MACD improving')
                elif macd_turning_up:
                    score += 5
                    reasons.append('MACD turning up')
                if constructive_volume:
                    score += 8
                    reasons.append('constructive volume')
                if volume_controlled:
                    score += 4
                    reasons.append('volume controlled')
                if timeframe_agreement_count >= 2:
                    score += 10
                    reasons.append('multi-timeframe confirmation')
                elif timeframe_agreement_count == 1:
                    score += 4
                if distance_to_neckline > 0.04:
                    score -= 6
                if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 3.0:
                    score -= 8

                snapshot = {
                    'close': self._pattern_snapshot_value(last_close),
                    'setup_stage': setup_stage,
                    'first_bottom': self._pattern_snapshot_value(first_bottom),
                    'second_bottom': self._pattern_snapshot_value(second_bottom),
                    'neckline': self._pattern_snapshot_value(neckline),
                    'bottom_gap_pct': self._pattern_snapshot_value(bottom_gap * 100.0),
                    'neckline_height_pct': self._pattern_snapshot_value(neckline_height * 100.0),
                    'distance_to_neckline_pct': self._pattern_snapshot_value(distance_to_neckline * 100.0),
                    'rebound_from_second_pct': self._pattern_snapshot_value(rebound_from_second * 100.0),
                    'prior_decline_pct': self._pattern_snapshot_value(prior_decline * 100.0) if prior_decline is not None else None,
                    'days_between_bottoms': separation,
                    'days_since_second_bottom': days_since_second,
                    'sma20': self._pattern_snapshot_value(sma20),
                    'sma50': self._pattern_snapshot_value(sma50),
                    'sma200': self._pattern_snapshot_value(sma200),
                    'ema21': self._pattern_snapshot_value(ema21),
                    'rsi14': self._pattern_snapshot_value(rsi),
                    'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
                    'rsi_state': 'recovering' if rsi_recovering else ('above RSI MA' if rsi_above_ma else 'mixed'),
                    'macd_line': self._pattern_snapshot_value(macd_line),
                    'macd_signal': self._pattern_snapshot_value(macd_signal),
                    'macd_histogram': self._pattern_snapshot_value(macd_hist),
                    'macd_state': 'improving' if macd_ok else ('turning up' if macd_turning_up else 'mixed'),
                    'volume20': self._pattern_snapshot_value(vol20, 0),
                    'volume50': self._pattern_snapshot_value(vol50, 0),
                    'volume120': self._pattern_snapshot_value(vol120, 0),
                    'volume_state': 'constructive' if constructive_volume else ('controlled' if volume_controlled else 'disorderly'),
                    'short_timeframe_confirmed': short_timeframe_ok,
                    'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
                    'long_timeframe_confirmed': long_timeframe_ok,
                    'timeframe_agreement': f'{timeframe_agreement_count}/3',
                }
                matched = bool(
                    indicator_confirmations >= 2
                    and timeframe_agreement_count >= 2
                    and score >= 62
                )
                bounded_score = max(0.0, min(100.0, score))
                if (
                    (matched and (not best_matched or bounded_score > best_score))
                    or (not best_matched and not matched and bounded_score > best_score)
                ):
                    best_score = bounded_score
                    best_reasons = reasons[:8]
                    best_snapshot = snapshot
                    best_matched = matched

        if not best_snapshot:
            return False, 0.0, [], {}
        return best_matched, best_score, best_reasons, best_snapshot

    def _evaluate_bullish_flag_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 90:
            return False, 0.0, [], {}
        high = pd.to_numeric(frame['High'], errors='coerce')
        low = pd.to_numeric(frame['Low'], errors='coerce')
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        if last_close is None or last_close <= 0:
            return False, 0.0, [], {}

        sma20_series = close.rolling(20, min_periods=20).mean()
        sma50_series = close.rolling(50, min_periods=50).mean()
        sma200_series = close.rolling(200, min_periods=180).mean()
        ema21_series = close.ewm(span=21, adjust=False, min_periods=21).mean()
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = volume.rolling(20, min_periods=10).mean()
        vol50_series = volume.rolling(50, min_periods=20).mean()
        vol120_series = volume.rolling(120, min_periods=60).mean()
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)

        rsi_series = self._calculate_rsi(close)
        rsi_ma_series = rsi_series.rolling(10, min_periods=5).mean()
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        rsi_change_20 = self._series_change(rsi_series, 20)
        macd_line_series, macd_signal_series, macd_hist_series = self._calculate_macd(close)
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        best_score = 0.0
        best_reasons: list[str] = []
        best_snapshot: dict[str, Any] = {}
        best_matched = False
        for pole_high_index in range(max(35, len(high) - 26), max(35, len(high) - 5)):
            flag_days = len(high) - 1 - pole_high_index
            if flag_days < 5 or flag_days > 25:
                continue
            pole_high = self._to_float(high.iloc[pole_high_index])
            pole_low_window = low.iloc[max(0, pole_high_index - 45):max(0, pole_high_index - 4)]
            pole_low = self._to_float(pole_low_window.min()) if not pole_low_window.dropna().empty else None
            if pole_high is None or pole_low is None or pole_high <= 0 or pole_low <= 0:
                continue
            flagpole_gain = (pole_high - pole_low) / pole_low
            if flagpole_gain < 0.12:
                continue

            flag_high = high.iloc[pole_high_index + 1:]
            flag_low_series = low.iloc[pole_high_index + 1:]
            if len(flag_high.dropna()) < 4 or len(flag_low_series.dropna()) < 4:
                continue
            flag_resistance = self._to_float(flag_high.max())
            flag_low = self._to_float(flag_low_series.min())
            if flag_resistance is None or flag_low is None or flag_resistance <= 0 or flag_low <= 0:
                continue
            pullback = (pole_high - flag_low) / pole_high
            if pullback < 0.03 or pullback > 0.18:
                continue
            if flag_low < pole_low + (pole_high - pole_low) * 0.35:
                continue
            if flag_resistance > pole_high * 1.025:
                continue

            distance_to_flag_resistance = (last_close - flag_resistance) / flag_resistance
            if distance_to_flag_resistance < -0.05 or distance_to_flag_resistance > 0.04:
                continue
            breakout = last_close >= flag_resistance * 1.002
            flag_close = close.iloc[pole_high_index + 1:]
            flag_volume = volume.iloc[pole_high_index + 1:]
            flag_vol_avg = self._to_float(flag_volume.mean())
            pole_vol_avg = self._to_float(volume.iloc[max(0, pole_high_index - 20):pole_high_index + 1].mean())
            orderly_volume = True
            if flag_vol_avg is not None and pole_vol_avg is not None and pole_vol_avg > 0:
                orderly_volume = flag_vol_avg <= pole_vol_avg * 1.25
            volume_controlled = True
            if latest_volume is not None and vol20 is not None and vol20 > 0:
                volume_controlled = latest_volume <= vol20 * 2.7
            volume_short_ok = bool(latest_volume is None or vol20 is None or latest_volume >= vol20 * 0.60)
            volume_intermediate_ok = bool(vol20 is None or vol50 is None or vol50 <= 0 or vol20 >= vol50 * 0.70)
            volume_long_ok = bool(vol50 is None or vol120 is None or vol120 <= 0 or vol50 >= vol120 * 0.65)
            volume_ok = bool(orderly_volume and volume_controlled)

            first_flag_high = self._to_float(flag_high.head(max(2, len(flag_high) // 2)).max())
            second_flag_high = self._to_float(flag_high.tail(max(2, len(flag_high) // 2)).max())
            controlled_flag = bool(first_flag_high is None or second_flag_high is None or second_flag_high <= first_flag_high * 1.025)
            flag_close_low = self._to_float(flag_close.min())
            still_supported = bool(
                flag_close_low is None
                or sma50 is None
                or flag_close_low >= sma50 * 0.94
                or flag_close_low >= pole_high * 0.82
            )

            uptrend_stack = bool(sma20 is not None and sma50 is not None and sma20 >= sma50 * 0.98)
            if sma200 is not None and sma50 is not None:
                uptrend_stack = uptrend_stack and sma50 >= sma200 * 0.95
            price_above_support = bool(
                (sma20 is None or last_close >= sma20 * 0.96)
                and (ema21 is None or last_close >= ema21 * 0.96)
                and (sma50 is None or last_close >= sma50 * 0.94)
            )

            rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
            rsi_constructive = bool(
                rsi is not None
                and 44 <= rsi <= 74
                and (rsi_above_ma or rsi_change_5 is None or rsi_change_5 >= -2.0)
            )
            rsi_short_ok = bool(rsi_constructive or (rsi_change_5 is not None and rsi_change_5 >= -1.5))
            rsi_intermediate_ok = bool(rsi is not None and rsi >= 45 and (rsi_change_20 is None or rsi_change_20 >= -5.0))
            rsi_long_ok = bool(rsi is not None and rsi >= 42)

            macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
            macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 >= -abs(last_close) * 0.001)
            macd_recovering = macd_line_change_20 is not None and macd_line_change_20 >= -abs(last_close) * 0.001
            macd_ok = bool(macd_above_signal or (macd_turning_up and macd_recovering))
            macd_short_ok = bool(macd_above_signal or macd_turning_up)
            macd_intermediate_ok = bool(macd_ok or (macd_hist is not None and macd_hist >= -abs(last_close) * 0.003))
            macd_long_ok = bool(macd_line is None or macd_line >= -abs(last_close) * 0.02 or macd_recovering)

            price_short_ok = bool(distance_to_flag_resistance >= -0.05)
            price_intermediate_ok = bool(price_above_support and still_supported)
            price_long_ok = bool(uptrend_stack or flagpole_gain >= 0.18)
            short_timeframe_ok = bool(price_short_ok and (rsi_short_ok or macd_short_ok or volume_short_ok))
            intermediate_timeframe_ok = bool(price_intermediate_ok and (rsi_intermediate_ok or macd_intermediate_ok or volume_intermediate_ok))
            long_timeframe_ok = bool(price_long_ok and (rsi_long_ok or macd_long_ok or volume_long_ok))
            timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
            indicator_confirmations = sum(1 for value in (rsi_constructive, macd_ok, volume_ok, timeframe_agreement_count >= 2) if value)

            setup_stage = 'Bullish Flag Breakout' if breakout else 'Bullish Flag Setup'
            score = 0.0
            reasons = []
            if flagpole_gain >= 0.20:
                score += 20
                reasons.append('strong flagpole')
            else:
                score += 14
                reasons.append('bullish flagpole')
            if 0.05 <= pullback <= 0.14:
                score += 18
                reasons.append('controlled pullback')
            else:
                score += 10
                reasons.append('acceptable pullback')
            if controlled_flag and still_supported:
                score += 14
                reasons.append('orderly flag')
            elif controlled_flag or still_supported:
                score += 8
            if breakout:
                score += 18
                reasons.append('flag breakout')
            else:
                score += 14
                reasons.append('near flag resistance')
            if uptrend_stack:
                score += 10
                reasons.append('uptrend MA structure')
            if rsi_constructive:
                score += 8
                reasons.append('RSI constructive')
            if macd_ok:
                score += 8
                reasons.append('MACD supportive')
            if orderly_volume:
                score += 6
                reasons.append('orderly volume')
            if volume_controlled:
                score += 4
                reasons.append('volume controlled')
            if timeframe_agreement_count >= 2:
                score += 10
                reasons.append('multi-timeframe confirmation')
            elif timeframe_agreement_count == 1:
                score += 4
            if latest_volume is not None and vol20 is not None and vol20 > 0 and latest_volume > vol20 * 2.7:
                score -= 8
            if rsi is not None and rsi > 76:
                score -= 8

            snapshot = {
                'close': self._pattern_snapshot_value(last_close),
                'setup_stage': setup_stage,
                'flagpole_gain_pct': self._pattern_snapshot_value(flagpole_gain * 100.0),
                'pullback_pct': self._pattern_snapshot_value(pullback * 100.0),
                'distance_to_flag_resistance_pct': self._pattern_snapshot_value(distance_to_flag_resistance * 100.0),
                'flag_resistance': self._pattern_snapshot_value(flag_resistance),
                'flag_days': flag_days,
                'sma20': self._pattern_snapshot_value(sma20),
                'sma50': self._pattern_snapshot_value(sma50),
                'sma200': self._pattern_snapshot_value(sma200),
                'ema21': self._pattern_snapshot_value(ema21),
                'rsi14': self._pattern_snapshot_value(rsi),
                'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
                'rsi_state': 'constructive' if rsi_constructive else ('above RSI MA' if rsi_above_ma else 'mixed'),
                'macd_line': self._pattern_snapshot_value(macd_line),
                'macd_signal': self._pattern_snapshot_value(macd_signal),
                'macd_histogram': self._pattern_snapshot_value(macd_hist),
                'macd_state': 'supportive' if macd_ok else ('turning up' if macd_turning_up else 'mixed'),
                'volume20': self._pattern_snapshot_value(vol20, 0),
                'volume50': self._pattern_snapshot_value(vol50, 0),
                'volume120': self._pattern_snapshot_value(vol120, 0),
                'volume_state': 'orderly' if orderly_volume else ('controlled' if volume_controlled else 'disorderly'),
                'short_timeframe_confirmed': short_timeframe_ok,
                'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
                'long_timeframe_confirmed': long_timeframe_ok,
                'timeframe_agreement': f'{timeframe_agreement_count}/3',
            }
            matched = bool(
                price_short_ok
                and price_intermediate_ok
                and indicator_confirmations >= 2
                and timeframe_agreement_count >= 2
                and score >= 62
            )
            bounded_score = max(0.0, min(100.0, score))
            if (
                (matched and (not best_matched or bounded_score > best_score))
                or (not best_matched and not matched and bounded_score > best_score)
            ):
                best_score = bounded_score
                best_reasons = reasons[:8]
                best_snapshot = snapshot
                best_matched = matched

        if not best_snapshot:
            return False, 0.0, [], {}
        return best_matched, best_score, best_reasons, best_snapshot

    def _evaluate_bullish_rsi_divergence_pattern(self, frame: Any) -> tuple[bool, float, list[str], dict[str, Any]]:
        if frame is None or getattr(frame, 'empty', True) or len(frame) < 90:
            return False, 0.0, [], {}
        high = pd.to_numeric(frame['High'], errors='coerce')
        low = pd.to_numeric(frame['Low'], errors='coerce')
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        if close.dropna().empty:
            return False, 0.0, [], {}

        last_close = self._to_float(close.iloc[-1])
        if last_close is None or last_close <= 0:
            return False, 0.0, [], {}

        sma20_series = close.rolling(20, min_periods=20).mean()
        sma50_series = close.rolling(50, min_periods=50).mean()
        sma200_series = close.rolling(200, min_periods=180).mean()
        ema21_series = close.ewm(span=21, adjust=False, min_periods=21).mean()
        sma20 = self._latest_series_value(sma20_series)
        sma50 = self._latest_series_value(sma50_series)
        sma200 = self._latest_series_value(sma200_series)
        ema21 = self._latest_series_value(ema21_series)
        vol20_series = volume.rolling(20, min_periods=10).mean()
        vol50_series = volume.rolling(50, min_periods=20).mean()
        vol120_series = volume.rolling(120, min_periods=60).mean()
        vol20 = self._latest_series_value(vol20_series)
        vol50 = self._latest_series_value(vol50_series)
        vol120 = self._latest_series_value(vol120_series)
        latest_volume = self._latest_series_value(volume)

        rsi_series = self._calculate_rsi(close)
        rsi_ma_series = rsi_series.rolling(10, min_periods=5).mean()
        rsi = self._latest_series_value(rsi_series)
        rsi_ma = self._latest_series_value(rsi_ma_series)
        rsi_change_5 = self._series_change(rsi_series, 5)
        macd_line_series, macd_signal_series, macd_hist_series = self._calculate_macd(close)
        macd_line = self._latest_series_value(macd_line_series)
        macd_signal = self._latest_series_value(macd_signal_series)
        macd_hist = self._latest_series_value(macd_hist_series)
        macd_hist_change_5 = self._series_change(macd_hist_series, 5)
        macd_line_change_20 = self._series_change(macd_line_series, 20)

        lookback_start = max(0, len(low) - 110)
        swing_lows = []
        for index in range(max(3, lookback_start), max(3, len(low) - 3)):
            low_value = self._to_float(low.iloc[index])
            if low_value is None or low_value <= 0:
                continue
            window = low.iloc[max(0, index - 3):min(len(low), index + 4)].dropna()
            if len(window) < 5:
                continue
            window_min = self._to_float(window.min())
            if window_min is not None and low_value <= window_min * 1.003:
                swing_lows.append(index)

        best_score = 0.0
        best_reasons: list[str] = []
        best_snapshot: dict[str, Any] = {}
        best_matched = False
        for first_index in swing_lows:
            for second_index in swing_lows:
                if second_index <= first_index:
                    continue
                separation = second_index - first_index
                days_since_second = len(low) - 1 - second_index
                if separation < 10 or separation > 70 or days_since_second < 3 or days_since_second > 40:
                    continue
                first_low = self._to_float(low.iloc[first_index])
                second_low = self._to_float(low.iloc[second_index])
                first_rsi = self._to_float(rsi_series.iloc[first_index])
                second_rsi = self._to_float(rsi_series.iloc[second_index])
                if None in (first_low, second_low, first_rsi, second_rsi) or not first_low or not second_low:
                    continue
                price_low_change = (second_low - first_low) / first_low
                rsi_divergence_points = second_rsi - first_rsi
                if price_low_change > 0.02 or price_low_change < -0.18 or rsi_divergence_points < 4.0:
                    continue
                post_second_low = self._to_float(low.iloc[second_index + 1:].min()) if second_index + 1 < len(low) else None
                if post_second_low is not None and post_second_low < second_low * 0.985:
                    continue
                rebound_from_second = (last_close - second_low) / second_low
                if rebound_from_second < 0.035:
                    continue

                trigger_candidates = []
                for value in (sma20, ema21):
                    if value is not None and value > 0:
                        trigger_candidates.append(value)
                recent_trigger = self._to_float(high.iloc[second_index + 1:].tail(12).max()) if second_index + 1 < len(high) else None
                if recent_trigger is not None and recent_trigger > 0:
                    trigger_candidates.append(recent_trigger)
                if not trigger_candidates:
                    continue
                trigger = min(trigger_candidates, key=lambda value: abs((last_close - value) / value))
                trigger_distance = (last_close - trigger) / trigger
                if trigger_distance < -0.045 or trigger_distance > 0.09:
                    continue

                recent_frame = frame.iloc[second_index:].copy()
                downside_volume_avg = None
                upside_volume_avg = None
                try:
                    recent_close = pd.to_numeric(recent_frame['Close'], errors='coerce')
                    recent_open = pd.to_numeric(recent_frame['Open'], errors='coerce') if 'Open' in recent_frame.columns else recent_close.shift(1)
                    recent_volume = pd.to_numeric(recent_frame['Volume'], errors='coerce')
                    downside_volume_avg = self._to_float(recent_volume[recent_close < recent_open].mean())
                    upside_volume_avg = self._to_float(recent_volume[recent_close >= recent_open].mean())
                except Exception:
                    pass
                volume_controlled = True
                if latest_volume is not None and vol20 is not None and vol20 > 0:
                    volume_controlled = latest_volume <= vol20 * 3.0
                selloff_disorderly = bool(
                    latest_volume is not None
                    and vol20 is not None
                    and vol20 > 0
                    and latest_volume > vol20 * 3.0
                    and last_close < close.iloc[-2]
                )
                constructive_volume = bool(
                    (upside_volume_avg is not None and downside_volume_avg is not None and downside_volume_avg > 0 and upside_volume_avg >= downside_volume_avg * 0.8)
                    or volume_controlled
                )
                volume_short_ok = bool(volume_controlled or latest_volume is None or vol20 is None)
                volume_intermediate_ok = bool(vol20 is None or vol50 is None or vol50 <= 0 or vol20 >= vol50 * 0.60)
                volume_long_ok = bool(vol50 is None or vol120 is None or vol120 <= 0 or vol50 >= vol120 * 0.55)

                rsi_above_ma = rsi is not None and rsi_ma is not None and rsi >= rsi_ma
                rsi_turning = bool(
                    rsi is not None
                    and 34 <= rsi <= 68
                    and (rsi_above_ma or rsi_change_5 is None or rsi_change_5 >= 0)
                )
                macd_above_signal = macd_line is not None and macd_signal is not None and macd_line >= macd_signal
                macd_turning_up = macd_hist is not None and (macd_hist_change_5 is None or macd_hist_change_5 > 0)
                macd_recovering = macd_line_change_20 is not None and macd_line_change_20 > 0
                macd_ok = bool(macd_above_signal or macd_turning_up or macd_recovering)

                price_short_ok = bool(rebound_from_second >= 0.05 and trigger_distance >= -0.045)
                price_intermediate_ok = bool(trigger_distance >= -0.03 or (sma20 is not None and last_close >= sma20 * 0.97))
                price_long_ok = bool(sma50 is None or last_close >= sma50 * 0.85 or trigger_distance >= 0)
                short_timeframe_ok = bool(price_short_ok and (rsi_turning or macd_turning_up or volume_short_ok))
                intermediate_timeframe_ok = bool(price_intermediate_ok and (rsi_above_ma or macd_ok or volume_intermediate_ok))
                long_timeframe_ok = bool(price_long_ok and (rsi is None or rsi >= 34 or macd_recovering or volume_long_ok))
                timeframe_agreement_count = sum(1 for value in (short_timeframe_ok, intermediate_timeframe_ok, long_timeframe_ok) if value)
                indicator_confirmations = sum(1 for value in (rsi_turning, macd_ok, constructive_volume, timeframe_agreement_count >= 2) if value)

                trigger_reclaimed = trigger_distance >= 0
                setup_stage = 'Bullish RSI Divergence Triggered' if trigger_reclaimed else 'Bullish RSI Divergence'
                score = 0.0
                reasons = []
                if price_low_change <= 0:
                    score += 18
                    reasons.append('lower price low')
                else:
                    score += 12
                    reasons.append('similar price low')
                if rsi_divergence_points >= 8:
                    score += 20
                    reasons.append('strong RSI divergence')
                else:
                    score += 14
                    reasons.append('RSI higher low')
                if trigger_reclaimed:
                    score += 18
                    reasons.append('trigger reclaimed')
                else:
                    score += 12
                    reasons.append('near trigger')
                if rebound_from_second >= 0.07:
                    score += 10
                    reasons.append('price rebound')
                else:
                    score += 5
                if days_since_second <= 25:
                    score += 8
                    reasons.append('fresh divergence')
                else:
                    score += 4
                if rsi_turning:
                    score += 10
                    reasons.append('RSI turning up')
                if macd_ok:
                    score += 8
                    reasons.append('MACD improving')
                if constructive_volume:
                    score += 6
                    reasons.append('volume stabilizing')
                if volume_controlled:
                    score += 4
                    reasons.append('volume controlled')
                if timeframe_agreement_count >= 2:
                    score += 10
                    reasons.append('multi-timeframe confirmation')
                elif timeframe_agreement_count == 1:
                    score += 4
                if selloff_disorderly:
                    score -= 14

                snapshot = {
                    'close': self._pattern_snapshot_value(last_close),
                    'setup_stage': setup_stage,
                    'first_low': self._pattern_snapshot_value(first_low),
                    'second_low': self._pattern_snapshot_value(second_low),
                    'price_low_change_pct': self._pattern_snapshot_value(price_low_change * 100.0),
                    'first_rsi': self._pattern_snapshot_value(first_rsi),
                    'second_rsi': self._pattern_snapshot_value(second_rsi),
                    'rsi_divergence_points': self._pattern_snapshot_value(rsi_divergence_points),
                    'trigger': self._pattern_snapshot_value(trigger),
                    'trigger_distance_pct': self._pattern_snapshot_value(trigger_distance * 100.0),
                    'rebound_from_second_pct': self._pattern_snapshot_value(rebound_from_second * 100.0),
                    'days_between_lows': separation,
                    'days_since_second_low': days_since_second,
                    'sma20': self._pattern_snapshot_value(sma20),
                    'sma50': self._pattern_snapshot_value(sma50),
                    'sma200': self._pattern_snapshot_value(sma200),
                    'ema21': self._pattern_snapshot_value(ema21),
                    'rsi14': self._pattern_snapshot_value(rsi),
                    'rsi_ma10': self._pattern_snapshot_value(rsi_ma),
                    'rsi_state': 'turning up' if rsi_turning else ('above RSI MA' if rsi_above_ma else 'mixed'),
                    'macd_line': self._pattern_snapshot_value(macd_line),
                    'macd_signal': self._pattern_snapshot_value(macd_signal),
                    'macd_histogram': self._pattern_snapshot_value(macd_hist),
                    'macd_state': 'improving' if macd_ok else 'mixed',
                    'volume20': self._pattern_snapshot_value(vol20, 0),
                    'volume50': self._pattern_snapshot_value(vol50, 0),
                    'volume120': self._pattern_snapshot_value(vol120, 0),
                    'volume_state': 'stabilizing' if constructive_volume else ('controlled' if volume_controlled else 'disorderly'),
                    'short_timeframe_confirmed': short_timeframe_ok,
                    'intermediate_timeframe_confirmed': intermediate_timeframe_ok,
                    'long_timeframe_confirmed': long_timeframe_ok,
                    'timeframe_agreement': f'{timeframe_agreement_count}/3',
                }
                matched = bool(
                    not selloff_disorderly
                    and indicator_confirmations >= 2
                    and timeframe_agreement_count >= 2
                    and score >= 62
                )
                bounded_score = max(0.0, min(100.0, score))
                if (
                    (matched and (not best_matched or bounded_score > best_score))
                    or (not best_matched and not matched and bounded_score > best_score)
                ):
                    best_score = bounded_score
                    best_reasons = reasons[:8]
                    best_snapshot = snapshot
                    best_matched = matched

        if not best_snapshot:
            return False, 0.0, [], {}
        return best_matched, best_score, best_reasons, best_snapshot

    def _apply_pattern_analysis(self, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.pattern_modes or not candidates:
            return candidates, {'active': False, 'fallback_reason': ''}
        symbols = [str(candidate.get('symbol') or '').upper().strip() for candidate in candidates if str(candidate.get('symbol') or '').strip()]
        batch_data = self._download_pattern_history(symbols)
        analyzed = []
        matched = []
        near_matches = []
        history_success_count = 0
        if self.pattern_modes.intersection({'double_bottom', 'bullish_flag', 'bullish_rsi_divergence'}):
            required_rows = 90
        elif self.pattern_modes.intersection({'consolidation', 'downtrend'}):
            required_rows = 70
        else:
            required_rows = 60
        for candidate in candidates:
            symbol = str(candidate.get('symbol') or '').upper().strip()
            frame = self._load_pattern_history(symbol, batch_data, symbols)
            if frame is not None and not getattr(frame, 'empty', True) and len(frame) >= required_rows:
                history_success_count += 1
            breakout_match, breakout_score, breakout_reasons, breakout_snapshot = self._evaluate_breakout_pattern(frame)
            consolidation_match, consolidation_score, consolidation_reasons, consolidation_snapshot = self._evaluate_consolidation_pattern(frame)
            downtrend_match, downtrend_score, downtrend_reasons, downtrend_snapshot = self._evaluate_downtrend_pattern(frame)
            if 'double_bottom' in self.pattern_modes:
                double_bottom_match, double_bottom_score, double_bottom_reasons, double_bottom_snapshot = self._evaluate_double_bottom_pattern(frame)
            else:
                double_bottom_match, double_bottom_score, double_bottom_reasons, double_bottom_snapshot = False, 0.0, [], {}
            if 'bullish_flag' in self.pattern_modes:
                bullish_flag_match, bullish_flag_score, bullish_flag_reasons, bullish_flag_snapshot = self._evaluate_bullish_flag_pattern(frame)
            else:
                bullish_flag_match, bullish_flag_score, bullish_flag_reasons, bullish_flag_snapshot = False, 0.0, [], {}
            if 'bullish_rsi_divergence' in self.pattern_modes:
                bullish_rsi_match, bullish_rsi_score, bullish_rsi_reasons, bullish_rsi_snapshot = self._evaluate_bullish_rsi_divergence_pattern(frame)
            else:
                bullish_rsi_match, bullish_rsi_score, bullish_rsi_reasons, bullish_rsi_snapshot = False, 0.0, [], {}
            pattern_type = ''
            pattern_score = 0.0
            pattern_reasons = []
            technical_snapshot = {}
            near_type = ''
            near_score = 0.0
            near_reasons = []
            near_snapshot = {}
            if 'breakout' in self.pattern_modes and breakout_match:
                pattern_type = str(breakout_snapshot.get('setup_stage') or 'Breakout Setup')
                pattern_score = breakout_score
                pattern_reasons = breakout_reasons
                technical_snapshot = {'breakout': breakout_snapshot}
            elif 'breakout' in self.pattern_modes and breakout_snapshot and breakout_score >= 50:
                stage = str(breakout_snapshot.get('setup_stage') or 'Breakout Setup')
                if stage not in ('Late Breakout', 'No Breakout'):
                    near_type = f'Near {stage}'
                    near_score = breakout_score
                    near_reasons = breakout_reasons
                    near_snapshot = {'breakout': breakout_snapshot}
            if 'consolidation' in self.pattern_modes and consolidation_match and consolidation_score >= pattern_score:
                pattern_type = 'Consolidation'
                pattern_score = consolidation_score
                pattern_reasons = consolidation_reasons
                technical_snapshot = {'consolidation': consolidation_snapshot}
            elif (
                'consolidation' in self.pattern_modes
                and not pattern_type
                and consolidation_snapshot
                and consolidation_score >= max(near_score, 55)
            ):
                near_type = 'Near Consolidation'
                near_score = consolidation_score
                near_reasons = consolidation_reasons
                near_snapshot = {'consolidation': consolidation_snapshot}
            if 'downtrend' in self.pattern_modes and downtrend_match and downtrend_score >= pattern_score:
                pattern_type = 'Downtrend'
                pattern_score = downtrend_score
                pattern_reasons = downtrend_reasons
                technical_snapshot = {'downtrend': downtrend_snapshot}
            elif (
                'downtrend' in self.pattern_modes
                and not pattern_type
                and downtrend_snapshot
                and downtrend_score >= max(near_score, 55)
            ):
                near_type = 'Near Downtrend'
                near_score = downtrend_score
                near_reasons = downtrend_reasons
                near_snapshot = {'downtrend': downtrend_snapshot}
            if 'double_bottom' in self.pattern_modes and double_bottom_match and double_bottom_score >= pattern_score:
                pattern_type = str(double_bottom_snapshot.get('setup_stage') or 'Double Bottom')
                pattern_score = double_bottom_score
                pattern_reasons = double_bottom_reasons
                technical_snapshot = {'double_bottom': double_bottom_snapshot}
            elif (
                'double_bottom' in self.pattern_modes
                and not pattern_type
                and double_bottom_snapshot
                and double_bottom_score >= max(near_score, 55)
            ):
                near_type = 'Near Double Bottom'
                near_score = double_bottom_score
                near_reasons = double_bottom_reasons
                near_snapshot = {'double_bottom': double_bottom_snapshot}
            if 'bullish_flag' in self.pattern_modes and bullish_flag_match and bullish_flag_score >= pattern_score:
                pattern_type = str(bullish_flag_snapshot.get('setup_stage') or 'Bullish Flag')
                pattern_score = bullish_flag_score
                pattern_reasons = bullish_flag_reasons
                technical_snapshot = {'bullish_flag': bullish_flag_snapshot}
            elif (
                'bullish_flag' in self.pattern_modes
                and not pattern_type
                and bullish_flag_snapshot
                and bullish_flag_score >= max(near_score, 55)
            ):
                near_type = 'Near Bullish Flag'
                near_score = bullish_flag_score
                near_reasons = bullish_flag_reasons
                near_snapshot = {'bullish_flag': bullish_flag_snapshot}
            if 'bullish_rsi_divergence' in self.pattern_modes and bullish_rsi_match and bullish_rsi_score >= pattern_score:
                pattern_type = str(bullish_rsi_snapshot.get('setup_stage') or 'Bullish RSI Divergence')
                pattern_score = bullish_rsi_score
                pattern_reasons = bullish_rsi_reasons
                technical_snapshot = {'bullish_rsi_divergence': bullish_rsi_snapshot}
            elif (
                'bullish_rsi_divergence' in self.pattern_modes
                and not pattern_type
                and bullish_rsi_snapshot
                and bullish_rsi_score >= max(near_score, 55)
            ):
                near_type = 'Near Bullish RSI Divergence'
                near_score = bullish_rsi_score
                near_reasons = bullish_rsi_reasons
                near_snapshot = {'bullish_rsi_divergence': bullish_rsi_snapshot}
            enriched = {
                **candidate,
                'pattern_match': bool(pattern_type),
                'pattern_type': pattern_type or near_type or 'None',
                'pattern_score': round(pattern_score or near_score, 1) if pattern_score or near_score else 0.0,
                'pattern_reasons': pattern_reasons or near_reasons,
                'technical_snapshot': technical_snapshot or near_snapshot,
            }
            analyzed.append(enriched)
            if enriched['pattern_match']:
                matched.append(enriched)
            elif near_type:
                near_matches.append({**enriched, 'pattern_match': True, 'pattern_type': near_type})

        if matched:
            matched.sort(key=lambda item: (float(item.get('pattern_score') or 0.0), float(item.get('score') or 0.0)), reverse=True)
            for index, candidate in enumerate(matched, start=1):
                candidate['rank'] = index
            return matched, {'active': True, 'fallback_reason': '', 'history_success_count': history_success_count}
        if near_matches:
            near_matches.sort(key=lambda item: (float(item.get('pattern_score') or 0.0), float(item.get('score') or 0.0)), reverse=True)
            for index, candidate in enumerate(near_matches, start=1):
                candidate['rank'] = index
                candidate['pattern_fallback_reason'] = 'No strict setup matched; loaded closest technical candidates.'
            return near_matches, {
                'active': True,
                'fallback_reason': 'No strict setup matched; loaded closest technical candidates.',
                'history_success_count': history_success_count,
            }
        if history_success_count <= 0:
            return analyzed, {
                'active': True,
                'fallback_reason': 'Technical pattern history was unavailable; showing balanced scored candidates.',
                'history_success_count': history_success_count,
            }
        for index, candidate in enumerate(analyzed, start=1):
            candidate['rank'] = index
            candidate['pattern_fallback_reason'] = 'No strong technical setup found; showing balanced scored candidates.'
        return analyzed, {
            'active': True,
            'fallback_reason': 'No strong technical setup found; showing balanced scored candidates.',
            'history_success_count': history_success_count,
        }

    def _load_payload_for_candidate(
        self,
        candidate: dict[str, Any],
        *,
        candidate_pool: list[dict[str, Any]],
        total: int,
        screening_summary: str,
    ) -> dict[str, Any] | None:
        symbol = str(candidate.get('symbol') or '').upper().strip()
        if not symbol:
            return None
        quote = dict(candidate.get('quote') or {})
        ticker_obj = yf.Ticker(symbol)
        info = self._load_info(ticker_obj, symbol, quote)
        if not quote:
            quote = self._fallback_quote_from_info(symbol, info)
            candidate = self._candidate_for_target(symbol, quote)
            for index, pool_candidate in enumerate(candidate_pool):
                if pool_candidate.get('symbol') == symbol:
                    candidate_pool[index] = {**candidate, 'rank': pool_candidate.get('rank', candidate.get('rank'))}
                    candidate = candidate_pool[index]
                    break
        if not self._valid_candidate(symbol, info, quote):
            return None
        website = str(info.get('website') or '').strip()
        ir_url = str(info.get('irWebsite') or '').strip()
        if not ir_url:
            ir_url = f'https://www.google.com/search?q={symbol}+investor+relations'
        top_options, top_options_status = self._load_top_options(ticker_obj, symbol)
        return {
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
            'candidate_score': candidate.get('score'),
            'candidate_reasons': list(candidate.get('reasons') or []),
            'candidate_rank': candidate.get('rank'),
            'candidate_pool': candidate_pool,
            'screening_summary': screening_summary,
            'pattern_modes': sorted(self.pattern_modes),
            'pattern_match': bool(candidate.get('pattern_match')),
            'pattern_type': candidate.get('pattern_type') or 'None',
            'pattern_score': candidate.get('pattern_score') or 0.0,
            'pattern_reasons': list(candidate.get('pattern_reasons') or []),
            'technical_snapshot': dict(candidate.get('technical_snapshot') or {}),
            'pattern_fallback_reason': candidate.get('pattern_fallback_reason') or '',
        }

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
        required = {'Open', 'High', 'Low', 'Close'}
        has_ohlc = required.issubset(set(history.columns))
        closes = history['Close'].dropna()
        if closes.empty:
            return {'dates': [], 'closes': []}
        dates = []
        opens = []
        highs = []
        lows = []
        close_values = []
        volumes = []
        for index_value, row in history.iterrows():
            close_value = row.get('Close')
            try:
                close_numeric = float(close_value)
            except Exception:
                continue
            if not math.isfinite(close_numeric):
                continue
            try:
                date_text = pd.Timestamp(index_value).strftime('%Y-%m-%d')
            except Exception:
                date_text = str(index_value)[:10]
            dates.append(date_text)
            close_values.append(close_numeric)
            if has_ohlc:
                for source, target in (
                    ('Open', opens),
                    ('High', highs),
                    ('Low', lows),
                ):
                    try:
                        value = float(row.get(source))
                    except Exception:
                        value = close_numeric
                    target.append(value if math.isfinite(value) else close_numeric)
            volume_value = 0.0
            if 'Volume' in history.columns:
                try:
                    volume_value = float(row.get('Volume') or 0.0)
                except Exception:
                    volume_value = 0.0
            volumes.append(volume_value if math.isfinite(volume_value) else 0.0)
        payload = {'dates': dates, 'closes': close_values, 'volumes': volumes}
        if has_ohlc and len(opens) == len(close_values) and len(highs) == len(close_values) and len(lows) == len(close_values):
            payload.update({'opens': opens, 'highs': highs, 'lows': lows})
        return payload

    def _load_top_option_for_expiry(self, ticker_obj: Any, symbol: str, expiry: str) -> dict[str, Any] | None:
        try:
            with YF_LOCK:
                chain = ticker_obj.option_chain(expiry)
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
            with YF_LOCK:
                expiries = [str(expiry or '').strip() for expiry in list(ticker_obj.options or []) if str(expiry or '').strip()]
        except Exception as exc:
            logger.info('Roll top options expirations unavailable for %s: %s', symbol, exc)
            return [], 'Top options unavailable: expirations could not be loaded.'
        if not expiries:
            return [], 'No options expirations were available for this ticker.'

        records_by_expiry = {}
        failed_count = 0
        scanned_expiries = expiries[:self._MAX_OPTION_EXPIRIES]
        for expiry in scanned_expiries:
            record = self._load_top_option_for_expiry(ticker_obj, symbol, expiry)
            if record is None:
                failed_count += 1
                continue
            records_by_expiry[expiry] = record

        records = [records_by_expiry[expiry] for expiry in scanned_expiries if expiry in records_by_expiry]
        if not records:
            return [], 'Top options unavailable: near-term option-chain loads failed.'
        status = ''
        if failed_count:
            status = f'Top options loaded for {len(records)} of {len(scanned_expiries)} near-term expirations.'
        return records, status

    def fetch(self) -> dict[str, Any]:
        query = self._query()
        total = self._screen_total(query)
        if total <= 0:
            raise RuntimeError('No liquid US equity candidates were returned by yfinance.')
        candidate_pool = self._build_candidate_pool(query, total)
        if not candidate_pool:
            quote = self._screen_quote(query, total)
            symbol = str(quote.get('symbol') or self.target_symbol or '').upper().strip()
            if not symbol:
                raise RuntimeError('Could not find a scored candidate with usable quote data.')
            candidate_pool = [self._candidate_for_target(symbol, quote)]
        if self.target_symbol and not any(candidate.get('symbol') == self.target_symbol for candidate in candidate_pool):
            target_candidate = {
                'symbol': self.target_symbol,
                'name': self.target_symbol,
                'sector': 'N/A',
                'score': 0.0,
                'reasons': ['selected candidate'],
                'rank': 0,
                'quote': {},
            }
            candidate_pool = [target_candidate] + candidate_pool

        pattern_status = {'active': False, 'fallback_reason': ''}
        if self.pattern_modes:
            pattern_pool, pattern_status = self._apply_pattern_analysis(candidate_pool)
            if pattern_pool:
                candidate_pool = pattern_pool
            elif pattern_status.get('fallback_reason'):
                for candidate in candidate_pool:
                    candidate['pattern_fallback_reason'] = str(pattern_status.get('fallback_reason') or '')
        screening_summary = (
            f'Scored {len(candidate_pool)} candidates from {total:,} yfinance-screened US equities '
            f'with market cap above $1B and 3-month average volume above 1M.'
        )
        if self.pattern_modes:
            mode_labels = {
                'breakout': 'breakout',
                'consolidation': 'consolidation',
                'downtrend': 'downtrend',
                'double_bottom': 'double bottom',
                'bullish_flag': 'bullish flag',
                'bullish_rsi_divergence': 'bullish RSI divergence',
            }
            mode_text = ' or '.join(mode_labels.get(mode, mode) for mode in sorted(self.pattern_modes))
            screening_summary = f'{screening_summary} Filtered for {mode_text} setups using 6-month daily history.'
        if pattern_status.get('fallback_reason'):
            for candidate in candidate_pool:
                candidate['pattern_fallback_reason'] = pattern_status.get('fallback_reason')
        selected = self._select_candidate(candidate_pool)
        payload = self._load_payload_for_candidate(
            selected,
            candidate_pool=candidate_pool,
            total=total,
            screening_summary=screening_summary,
        )
        if payload is not None:
            return payload

        for candidate in candidate_pool:
            payload = self._load_payload_for_candidate(
                candidate,
                candidate_pool=candidate_pool,
                total=total,
                screening_summary=screening_summary,
            )
            if payload is not None:
                return payload
        raise RuntimeError('Could not find a scored candidate with usable company and price data.')

    def run(self) -> None:
        try:
            self.finished.emit(self.fetch())
        except Exception as exc:
            self.error.emit(f'Random roll failed: {exc}')
