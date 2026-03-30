from __future__ import annotations
from typing import Any
from ..dependencies import *


class PreMarketWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, watchlist: list[str] | None = None) -> None:
        super().__init__()
        self.watchlist = watchlist or []

    def run(self) -> None:
        try:
            result: dict[str, Any] = {}
            result['futures'] = self._fetch_futures()
            result['dxy'] = self._fetch_dxy()
            result['tnx'] = self._fetch_tnx()
            result['vix'] = self._fetch_vix()
            result['fear_greed'] = self._fetch_fear_greed()
            result['spy_momentum'] = self._fetch_spy_momentum()
            self.finished.emit(result)
        except Exception as ex:
            logger.error(f'PreMarketWorker error: {ex}')
            self.error.emit(str(ex))

    def _fetch_futures(self) -> list[dict]:
        rows = []
        names = {'ES=F': 'S&P 500', 'NQ=F': 'Nasdaq 100', 'YM=F': 'Dow Jones'}
        for ticker in ('ES=F', 'NQ=F', 'YM=F'):
            try:
                with YF_LOCK:
                    df = yf.Ticker(ticker).history(period='2d', interval='1h')
                if df is None or df.empty or len(df) < 2:
                    continue
                closes = df['Close'].dropna()
                current = float(closes.iloc[-1])
                prior_day = df[df.index.date < df.index.date[-1]]
                if prior_day.empty:
                    prior_close = float(closes.iloc[0])
                else:
                    prior_close = float(prior_day['Close'].dropna().iloc[-1])
                chg_pct = (current - prior_close) / prior_close * 100 if prior_close else 0
                direction = 'Up' if chg_pct > 0.05 else ('Down' if chg_pct < -0.05 else 'Flat')
                rows.append({'ticker': ticker, 'name': names.get(ticker, ''), 'price': current, 'change_pct': chg_pct, 'direction': direction})
            except Exception as ex:
                logger.warning(f'Futures fetch error {ticker}: {ex}')
        return rows

    def _fetch_dxy(self) -> dict:
        try:
            t = yf.Ticker('DX-Y.NYB')
            with YF_LOCK:
                df = t.history(period='10d', interval='1d')
            if df is None or df.empty:
                return {}
            closes = df['Close'].dropna()
            if len(closes) < 2:
                return {}
            level = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            chg_1d = (level - prev) / prev * 100
            if len(closes) >= 5:
                slope = float(closes.iloc[-1]) - float(closes.iloc[-5])
                trend = 'Strengthening' if slope > 0.1 else ('Weakening' if slope < -0.1 else 'Flat')
            else:
                trend = '--'
            return {'level': level, 'change_1d': chg_1d, 'trend': trend}
        except Exception as ex:
            logger.warning(f'DXY fetch error: {ex}')
            return {}

    def _fetch_tnx(self) -> dict:
        try:
            t = yf.Ticker('^TNX')
            with YF_LOCK:
                df = t.history(period='30d', interval='1d')
            if df is None or df.empty:
                return {}
            closes = df['Close'].dropna()
            if len(closes) < 2:
                return {}
            current = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            chg_bps = (current - prev) * 100
            avg_20 = float(closes.tail(20).mean()) if len(closes) >= 20 else float(closes.mean())
            vs_avg = current - avg_20
            return {'yield': current, 'change_bps': chg_bps, 'avg_20d': avg_20, 'vs_avg': vs_avg}
        except Exception as ex:
            logger.warning(f'TNX fetch error: {ex}')
            return {}

    def _fetch_vix(self) -> dict:
        try:
            t = yf.Ticker('^VIX')
            with YF_LOCK:
                df = t.history(period='5d', interval='1d')
            if df is None or df.empty:
                return {}
            closes = df['Close'].dropna()
            if len(closes) < 2:
                return {}
            level = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            chg = level - prev
            if level < 15:
                regime = 'Low Vol'
            elif level < 20:
                regime = 'Normal'
            elif level < 30:
                regime = 'Elevated'
            else:
                regime = 'High Vol'
            return {'level': level, 'change': chg, 'regime': regime}
        except Exception as ex:
            logger.warning(f'VIX fetch error: {ex}')
            return {}

    def _fetch_spy_momentum(self) -> dict:
        try:
            return self._fetch_spy_yfinance()
        except Exception as ex:
            logger.warning(f'SPY momentum fetch failed: {ex}')
            return {}

    def _fetch_spy_yfinance(self) -> dict:
        """Fallback: fetch SPY data via yfinance."""
        with YF_LOCK:
            df = yf.download('SPY', period='2y', interval='1d', progress=False)
        if df is None or df.empty:
            return {}
        closes = df['Close'].squeeze().dropna()
        if len(closes) < 2:
            return {}
        ma125 = closes.rolling(125).mean()
        dates = [d.to_pydatetime() for d in closes.index]
        last_close = float(closes.iloc[-1])
        last_ma = float(ma125.iloc[-1]) if not pd.isna(ma125.iloc[-1]) else None
        return {
            'dates': dates,
            'closes': closes.tolist(),
            'ma125': ma125.tolist(),
            'last_close': last_close,
            'last_ma': last_ma,
        }

    @staticmethod
    def _fg_rating(score: float | None) -> str:
        if score is None:
            return '--'
        if score < 25:
            return 'Extreme Fear'
        if score < 45:
            return 'Fear'
        if score < 55:
            return 'Neutral'
        if score < 75:
            return 'Greed'
        return 'Extreme Greed'

    def _fetch_fear_greed(self) -> dict:
        try:
            url = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Referer': 'https://edition.cnn.com/markets/fear-and-greed',
            }
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            fg = data.get('fear_and_greed', {})
            score = fg.get('score')
            rating = fg.get('rating', '--')
            if score is not None:
                score = round(float(score), 1)
            ts = fg.get('timestamp', '')
            ts_display = ''
            if ts:
                try:
                    dt = datetime.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                    et = ZoneInfo('America/New_York')
                    ts_display = dt.astimezone(et).strftime('%b %d at %I:%M:%S %p ET')
                except Exception:
                    ts_display = str(ts)
            history = []
            for key, label in [
                ('previous_close', 'Previous close'),
                ('previous_1_week', '1 week ago'),
                ('previous_1_month', '1 month ago'),
                ('previous_1_year', '1 year ago'),
            ]:
                h_score = fg.get(key)
                if h_score is not None:
                    h_score = round(float(h_score), 1)
                history.append({
                    'period': label,
                    'score': h_score,
                    'rating': self._fg_rating(h_score),
                })
            return {
                'score': score,
                'rating': rating.title() if isinstance(rating, str) else '--',
                'timestamp': ts_display,
                'history': history,
            }
        except Exception as ex:
            logger.warning(f'Fear & Greed fetch error: {ex}')
            return {}
