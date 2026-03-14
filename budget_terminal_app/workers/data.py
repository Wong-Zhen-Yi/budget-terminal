from __future__ import annotations
from typing import Any
from ..constants import *
from ..dependencies import *
from ..persistence import fmt_num
from ..cache import CacheManager

class DataWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, tickers: Any, chart_configs: Any, request_id: int=0) -> None:
        """Initialize the object."""
        super().__init__()
        self.tickers = tickers
        self.chart_configs = chart_configs
        self.request_id = int(request_id)

    def run(self) -> Any:
        """Handle run."""
        try:
            logger.info(f'Worker starting. Tickers: {self.tickers}, Charts: {self.chart_configs}')
            dashboard_chart_configs = []
            if isinstance(self.chart_configs, (list, tuple)):
                for config in self.chart_configs:
                    if isinstance(config, (list, tuple)) and len(config) >= 3:
                        dashboard_chart_configs.append((config[0], config[1], config[2]))
            elif isinstance(self.chart_configs, dict):
                symbol = self.chart_configs.get('symbol')
                period = self.chart_configs.get('period')
                interval = self.chart_configs.get('interval')
                if symbol and period and interval:
                    dashboard_chart_configs.append((symbol, period, interval))
            dashboard_chart_config = next((cfg for cfg in dashboard_chart_configs if str(cfg[0] or '').strip()), None)
            data = {
                'request_id': self.request_id,
                'chart_configs': list(dashboard_chart_configs),
            }
            all_symbols = []
            for symbol in self.tickers + ['SPY', 'QQQ', '^VIX', 'GLD', 'CL=F']:
                if symbol not in all_symbols:
                    all_symbols.append(symbol)
            logger.debug(f'Downloading batch data for: {all_symbols}')
            batch_data = yf.download(all_symbols, period='5d', interval='1d', group_by='ticker', progress=False, prepost=True)
            portfolio_info = {}
            _is_multi = isinstance(batch_data.columns, pd.MultiIndex)

            def _get_batch_close(symbol: Any) -> Any:
                """Return a symbol-specific close series from a batch download when available."""
                if batch_data is None or batch_data.empty:
                    return None
                if _is_multi:
                    level_zero = batch_data.columns.get_level_values(0)
                    level_one = batch_data.columns.get_level_values(1)
                    if symbol in level_zero:
                        symbol_frame = batch_data[symbol]
                    elif symbol in level_one:
                        symbol_frame = batch_data.xs(symbol, axis=1, level=1)
                    else:
                        return None
                    if 'Close' not in symbol_frame.columns:
                        return None
                    return symbol_frame['Close'].dropna()
                if symbol in batch_data.columns:
                    return batch_data[symbol].dropna()
                if len(all_symbols) == 1 and 'Close' in batch_data.columns and all_symbols[0] == symbol:
                    return batch_data['Close'].dropna()
                return None

            for t in self.tickers:
                try:
                    close = _get_batch_close(t)
                    if close is None or close.empty:
                        close = yf.Ticker(t).history(period='5d')['Close'].dropna()
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
                    close = _get_batch_close(idx)
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
            chart_option_expirations = {}

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

            def _normalize_chart_frame(symbol: Any, df: Any) -> Any:
                """Normalize a single-symbol OHLC frame or reject it as ambiguous."""
                if df is None or df.empty:
                    return None
                frame = df.copy()
                if isinstance(frame.columns, pd.MultiIndex):
                    level_zero = list(frame.columns.get_level_values(0))
                    level_one = list(frame.columns.get_level_values(1))
                    if symbol in level_zero:
                        frame = frame.xs(symbol, axis=1, level=0, drop_level=True).copy()
                    elif symbol in level_one:
                        frame = frame.xs(symbol, axis=1, level=1, drop_level=True).copy()
                    else:
                        logger.warning('Dashboard chart %s rejected ambiguous MultiIndex columns: %s', symbol, list(frame.columns))
                        return None
                frame = _normalize_close_frame(frame)
                rename_map = {}
                for column in list(frame.columns):
                    lowered = str(column).strip().lower()
                    if lowered == 'open':
                        rename_map[column] = 'Open'
                    elif lowered == 'high':
                        rename_map[column] = 'High'
                    elif lowered == 'low':
                        rename_map[column] = 'Low'
                    elif lowered == 'close':
                        rename_map[column] = 'Close'
                    elif lowered == 'volume':
                        rename_map[column] = 'Volume'
                if rename_map:
                    frame = frame.rename(columns=rename_map)
                required_columns = ['Open', 'High', 'Low', 'Close']
                missing_columns = [column for column in required_columns if column not in frame.columns]
                if missing_columns:
                    logger.warning('Dashboard chart %s rejected frame missing columns %s. Columns=%s', symbol, missing_columns, list(frame.columns))
                    return None
                try:
                    frame.index = pd.to_datetime(frame.index)
                except Exception:
                    logger.warning('Dashboard chart %s rejected non-datetime index.', symbol)
                    return None
                frame = frame.sort_index()
                frame = frame.dropna(subset=required_columns).copy()
                if frame.empty:
                    logger.warning('Dashboard chart %s rejected empty OHLC frame after normalization.', symbol)
                    return None
                ordered_columns = required_columns + [column for column in frame.columns if column not in required_columns]
                return frame.loc[:, ordered_columns]

            def _build_daily_ma200(ct: Any, source_df: Any, cache: Any) -> Any:
                """Build a daily 200 MA aligned to the chart timeframe index."""
                daily_df = cache.get_data(ct, '1d')
                if daily_df is None or daily_df.empty:
                    daily_df = yf.download(ct, period='5y', interval='1d', progress=False, auto_adjust=False)
                    if daily_df is not None and not daily_df.empty:
                        cache.save_data(ct, '1d', daily_df)
                daily_df = _normalize_chart_frame(ct, daily_df)
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

            def _load_options_chain(cache: Any, ticker: Any, expiry: Any, ticker_obj: Any=None) -> Any:
                """Load one options chain from cache or Yahoo and normalize contract metadata."""
                opts_df = cache.get_options_chain(ticker, expiry)
                if opts_df is None:
                    if ticker_obj is None:
                        ticker_obj = yf.Ticker(ticker)
                    chain = ticker_obj.option_chain(expiry)
                    calls = chain.calls.copy()
                    puts = chain.puts.copy()
                    calls['ticker'], calls['type'] = (ticker, 'Call')
                    puts['ticker'], puts['type'] = (ticker, 'Put')
                    opts_df = pd.concat([calls, puts], ignore_index=True)
                    opts_df['expiration'] = expiry
                    cache.save_options_chain(ticker, expiry, opts_df)
                else:
                    opts_df = opts_df.copy()
                if 'ticker' not in opts_df.columns:
                    opts_df['ticker'] = ticker
                if 'type' not in opts_df.columns:
                    opts_df['type'] = ''
                if 'expiration' not in opts_df.columns:
                    opts_df['expiration'] = expiry
                return opts_df

            def _select_option_expiry_buckets(expirations: Any) -> Any:
                """Map available expirations to the requested dashboard horizon buckets."""
                if not expirations:
                    return {}
                today = datetime.date.today()
                parsed = []
                for expiry in expirations:
                    try:
                        expiry_text = str(expiry)
                        expiry_date = datetime.date.fromisoformat(expiry_text)
                    except Exception:
                        continue
                    parsed.append((expiry_text, expiry_date))
                if not parsed:
                    return {}
                parsed.sort(key=lambda item: item[1])
                buckets = {}
                for key, days_out in (('0_week', 0), ('2_weeks', 14), ('4_weeks', 28)):
                    target_date = today + datetime.timedelta(days=days_out)
                    selected = next((expiry for expiry, expiry_date in parsed if expiry_date >= target_date), None)
                    if selected is None and parsed:
                        selected = parsed[-1][0]
                    buckets[key] = selected
                return buckets

            def fetch_chart_and_options(config: Any) -> Any:
                """Fetch chart and options."""
                ct, period, interval = config
                if not ct:
                    return None
                cache = CacheManager()
                source_label = 'cache'
                raw_df = cache.get_data(ct, interval)
                df = _normalize_chart_frame(ct, raw_df)
                if df is None:
                    if raw_df is not None:
                        logger.info('Dashboard chart %s cache rejected for interval %s. Refetching.', ct, interval)
                    source_label = 'download'
                    raw_df = yf.download(ct, period=period, interval=interval, progress=False)
                    df = _normalize_chart_frame(ct, raw_df)
                    if df is not None and interval in ['1d', '1wk', '1mo']:
                        cache.save_data(ct, interval, df)
                if df is None:
                    logger.warning('Dashboard chart %s unavailable after %s for period=%s interval=%s.', ct, source_label, period, interval)
                    return (ct, None, {'0_week': [], '2_weeks': [], '4_weeks': []}, {}, None)
                logger.info(
                    'Dashboard chart %s loaded from %s with %s rows. Columns=%s last_close=%.2f',
                    ct,
                    source_label,
                    len(df),
                    list(df.columns),
                    float(df['Close'].iloc[-1]),
                )
                ma200_series = _build_daily_ma200(ct, df, cache) if not df.empty else pd.Series(dtype=float)
                option_buckets = {'0_week': [], '2_weeks': [], '4_weeks': []}
                option_expirations = {}
                try:
                    exps = cache.get_options_expiries(ct)
                    t_obj = None
                    if exps is None:
                        t_obj = yf.Ticker(ct)
                        exps = t_obj.options
                        cache.save_options_expiries(ct, exps)
                    expiry_buckets = _select_option_expiry_buckets(exps)
                    for bucket_name in option_buckets:
                        expiry = expiry_buckets.get(bucket_name)
                        if not expiry:
                            continue
                        option_expirations[bucket_name] = expiry
                        opts_df = _load_options_chain(cache, ct, expiry, ticker_obj=t_obj)
                        if opts_df is None or opts_df.empty:
                            continue
                        if 'volume' not in opts_df.columns:
                            continue
                        top_opts = opts_df.sort_values(by='volume', ascending=False).head(10)
                        option_buckets[bucket_name] = top_opts.to_dict('records')
                except Exception as exc:
                    logger.info('Dashboard options unavailable for %s: %s', ct, exc)
                return (ct, df, option_buckets, option_expirations, ma200_series)
            chart_results = []
            if dashboard_chart_config:
                chart_results.append(fetch_chart_and_options(dashboard_chart_config))
            for res in chart_results:
                if res:
                    ct, df, opts, option_exps, ma200 = res
                    charts[ct] = df
                    chart_options[ct] = opts
                    chart_option_expirations[ct] = option_exps
                    chart_ma200[ct] = ma200
            data['charts'] = charts
            data['chart_options'] = chart_options
            data['chart_option_expirations'] = chart_option_expirations
            data['chart_ma200'] = chart_ma200
            self.finished.emit(data)
        except Exception as e:
            logger.error(f'Worker error: {e}')
            self.error.emit(str(e))
