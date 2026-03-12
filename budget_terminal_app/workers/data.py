from __future__ import annotations
from typing import Any
from ..constants import *
from ..dependencies import *
from ..persistence import fmt_num
from ..cache import CacheManager

class DataWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, tickers: Any, chart_configs: Any) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers
        self.chart_configs = chart_configs

    def run(self) -> Any:
        """Handle run."""
        try:
            logger.info(f'Worker starting. Tickers: {self.tickers}, Charts: {self.chart_configs}')
            data = {}
            all_symbols = list(set(self.tickers + ['SPY', 'QQQ', '^VIX', 'GLD', 'CL=F']))
            logger.debug(f'Downloading batch data for: {all_symbols}')
            batch_data = yf.download(all_symbols, period='5d', interval='1d', group_by='ticker', progress=False, prepost=True)
            portfolio_info = {}
            _is_multi = isinstance(batch_data.columns, pd.MultiIndex)
            for t in self.tickers:
                try:
                    if _is_multi:
                        if t not in batch_data.columns.get_level_values(0):
                            close = yf.Ticker(t).history(period='5d')['Close'].dropna()
                        else:
                            close = batch_data[t]['Close'].dropna()
                    elif 'Close' not in batch_data.columns:
                        close = yf.Ticker(t).history(period='5d')['Close'].dropna()
                    elif t in batch_data.columns:
                        close = batch_data[t].dropna()
                    else:
                        close = batch_data['Close'].dropna()
                    if len(close) >= 2:
                        curr = float(close.iloc[-1])
                        prev = float(close.iloc[-2])
                        pct = (curr - prev) / prev * 100
                        portfolio_info[t] = {'price': curr, 'change': pct, 'abs_change': curr - prev}
                    elif len(close) == 1:
                        curr = float(close.iloc[-1])
                        portfolio_info[t] = {'price': curr, 'change': 0.0, 'abs_change': 0.0}
                except Exception:
                    continue
            data['portfolio'] = portfolio_info
            market_data = {}
            idx_map = {'SPY': 'SPY', 'QQQ': 'QQQ', '^VIX': 'VIX', 'GLD': 'GLD', 'CL=F': 'WTI'}
            for idx, display_name in idx_map.items():
                try:
                    close = None
                    if _is_multi and idx in batch_data.columns.get_level_values(0):
                        close = batch_data[idx]['Close'].dropna()
                    elif not _is_multi and idx in self.tickers + ['SPY', 'QQQ', '^VIX', 'GLD', 'CL=F']:
                        if idx in batch_data.columns:
                            close = batch_data[idx].dropna()
                    if close is None or len(close) < 2:
                        fallback = yf.Ticker(idx).history(period='5d', interval='1d')
                        if not fallback.empty:
                            close = fallback['Close'].dropna()
                    if close is not None and len(close) >= 2:
                        curr = float(close.iloc[-1])
                        prev = float(close.iloc[-2])
                        change = (curr - prev) / prev * 100
                        market_data[display_name] = {'price': curr, 'change': change}
                    elif close is not None and len(close) == 1:
                        market_data[display_name] = {'price': float(close.iloc[-1]), 'change': 0.0}
                except Exception:
                    pass
            data['market'] = market_data
            targets = []
            news_list = []

            def _parse_news_item(n: Any, ticker: Any, category: Any) -> Any:
                """Handle parse news item."""
                content = n.get('content') or {}
                title = content.get('title') or n.get('title', 'N/A')
                source = content.get('provider', {}).get('displayName') or n.get('publisher', 'N/A')
                pub_date_str = content.get('pubDate') or n.get('providerPublishTime', '')
                time_str = '--:--'
                ts = 0
                if isinstance(pub_date_str, (int, float)):
                    ts = pub_date_str
                    try:
                        dt = datetime.datetime.fromtimestamp(pub_date_str)
                        time_str = dt.strftime('%H:%M')
                    except:
                        pass
                elif pub_date_str:
                    try:
                        dt = datetime.datetime.fromisoformat(str(pub_date_str).replace('Z', '+00:00'))
                        time_str = dt.strftime('%H:%M')
                        ts = dt.timestamp()
                    except:
                        time_str = str(pub_date_str)[:10]
                url_data = content.get('canonicalUrl') or content.get('clickThroughUrl') or n.get('link', '')
                url = url_data.get('url', '') if isinstance(url_data, dict) else str(url_data)
                return {'ticker': ticker, 'title': title, 'source': source, 'time': time_str, 'url': url, 'category': category, '_ts': ts}

            def fetch_stock_details(t: Any) -> Any:
                """Fetch stock details."""
                try:
                    ticker_obj = yf.Ticker(t)
                    info = ticker_obj.info
                    target = info.get('targetMeanPrice', 'N/A')
                    details = {'targets': {'ticker': t, 'current': portfolio_info.get(t, {}).get('price', 0), 'target': target}, 'news': []}
                    for n in ticker_obj.news[:5]:
                        try:
                            details['news'].append(_parse_news_item(n, t, 'portfolio'))
                        except:
                            continue
                    return details
                except Exception:
                    return None
            with ThreadPoolExecutor(max_workers=30) as executor:
                results = list(executor.map(fetch_stock_details, self.tickers))
            for res in results:
                if res:
                    targets.append(res['targets'])
                    news_list.extend(res['news'])
            data['targets'] = targets
            MACRO_TICKERS = ['SPY', 'QQQ', 'GLD', 'CL=F', '^VIX', '^TNX', 'DX-Y.NYB']

            def fetch_macro_news(t: Any) -> Any:
                """Fetch macro news."""
                articles = []
                try:
                    for n in yf.Ticker(t).news[:5]:
                        try:
                            articles.append(_parse_news_item(n, t, 'macro'))
                        except:
                            continue
                except:
                    pass
                return articles
            with ThreadPoolExecutor(max_workers=30) as executor:
                macro_results = list(executor.map(fetch_macro_news, MACRO_TICKERS))
            for articles in macro_results:
                news_list.extend(articles)
            data['news'] = news_list
            charts = {}
            chart_options = {}
            chart_ma200 = {}

            def _normalize_close_frame(df: Any) -> Any:
                """Normalize a downloaded frame so Close can be referenced reliably."""
                if df is None or df.empty:
                    return df
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                rename_map = {}
                for column in list(df.columns):
                    if str(column).strip().lower() == 'close':
                        rename_map[column] = 'Close'
                if rename_map:
                    df = df.rename(columns=rename_map)
                return df

            def _build_daily_ma200(ct: Any, source_df: Any, cache: Any) -> Any:
                """Build a daily 200 MA aligned to the chart timeframe index."""
                daily_df = cache.get_data(ct, '1d')
                if daily_df is None or daily_df.empty:
                    daily_df = yf.download(ct, period='5y', interval='1d', progress=False, auto_adjust=False)
                    if daily_df is not None and not daily_df.empty:
                        cache.save_data(ct, '1d', daily_df)
                daily_df = _normalize_close_frame(daily_df)
                if daily_df is None or daily_df.empty or 'Close' not in daily_df.columns:
                    return pd.Series(index=source_df.index, dtype=float)
                daily_df = daily_df.dropna(subset=['Close']).copy()
                if daily_df.empty:
                    return pd.Series(index=source_df.index, dtype=float)
                daily_ma = pd.Series(daily_df['Close']).astype(float).rolling(200, min_periods=200).mean().dropna()
                if daily_ma.empty:
                    return pd.Series(index=source_df.index, dtype=float)
                source_index = pd.DatetimeIndex(pd.to_datetime(source_df.index))
                daily_index = pd.DatetimeIndex(pd.to_datetime(daily_ma.index))
                if getattr(source_index, 'tz', None) is not None:
                    source_index = source_index.tz_localize(None)
                if getattr(daily_index, 'tz', None) is not None:
                    daily_index = daily_index.tz_localize(None)
                source_frame = pd.DataFrame(index=source_index).sort_index()
                daily_frame = pd.DataFrame({'ma200': list(daily_ma.values)}, index=daily_index).sort_index()
                aligned = pd.merge_asof(source_frame, daily_frame, left_index=True, right_index=True, direction='backward')['ma200']
                aligned.index = source_df.index
                return aligned

            def fetch_chart_and_options(config: Any) -> Any:
                """Fetch chart and options."""
                ct, period, interval = config
                if not ct:
                    return None
                cache = CacheManager()
                df = cache.get_data(ct, interval)
                if df is None:
                    df = yf.download(ct, period=period, interval=interval, progress=False)
                    if not df.empty and interval in ['1d', '1wk', '1mo']:
                        cache.save_data(ct, interval, df)
                ma200_series = _build_daily_ma200(ct, df, cache) if df is not None and not df.empty else pd.Series(dtype=float)
                opt_records = []
                try:
                    exps = cache.get_options_expiries(ct)
                    t_obj = None
                    if exps is None:
                        t_obj = yf.Ticker(ct)
                        exps = t_obj.options
                        cache.save_options_expiries(ct, exps)
                    if exps:
                        opts_df = cache.get_options_chain(ct, exps[0])
                        if opts_df is None:
                            if t_obj is None:
                                t_obj = yf.Ticker(ct)
                            chain = t_obj.option_chain(exps[0])
                            c, p = (chain.calls.copy(), chain.puts.copy())
                            c['ticker'], c['type'] = (ct, 'Call')
                            p['ticker'], p['type'] = (ct, 'Put')
                            opts_df = pd.concat([c, p])
                            opts_df['expiration'] = exps[0]
                            cache.save_options_chain(ct, exps[0], opts_df)
                        top_opts = opts_df.sort_values(by='volume', ascending=False).head(10)
                        opt_records = top_opts.to_dict('records')
                except Exception:
                    pass
                return (ct, df, opt_records, ma200_series)
            with ThreadPoolExecutor(max_workers=3) as executor:
                chart_results = list(executor.map(fetch_chart_and_options, self.chart_configs))
            for res in chart_results:
                if res:
                    ct, df, opts, ma200 = res
                    charts[ct] = df
                    chart_options[ct] = opts
                    chart_ma200[ct] = ma200
            data['charts'] = charts
            data['chart_options'] = chart_options
            data['chart_ma200'] = chart_ma200
            self.finished.emit(data)
        except Exception as e:
            logger.error(f'Worker error: {e}')
            self.error.emit(str(e))
