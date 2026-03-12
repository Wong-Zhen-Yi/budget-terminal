from __future__ import annotations
from typing import Any
from .dependencies import *

class CacheManager:

    def __init__(self, db_path: Any='budget_cache.db') -> None:
        """Initialize the object."""
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Handle init db."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('\n                    CREATE TABLE IF NOT EXISTS meta (\n                        ticker TEXT,\n                        interval TEXT,\n                        last_updated TIMESTAMP,\n                        PRIMARY KEY (ticker, interval)\n                    )\n                ')
                conn.execute('\n                    CREATE TABLE IF NOT EXISTS meta_options (\n                        ticker TEXT PRIMARY KEY,\n                        expirations TEXT,\n                        last_updated TIMESTAMP\n                    )\n                ')
        except Exception as e:
            logger.error(f'Failed to initialize cache DB: {e}')

    def get_data(self, ticker: Any, interval: Any, max_age_hours: Any=24) -> Any:
        """Handle get data."""
        safe_ticker = ticker.replace('^', 'IDX_').replace('=', 'FX_').replace('/', '_').replace('-', '_')
        table_name = f'cache_{safe_ticker}_{interval}'
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT last_updated FROM meta WHERE ticker=? AND interval=?', (ticker, interval))
                row = cursor.fetchone()
                if row:
                    last_updated = datetime.datetime.fromisoformat(row[0])
                    if (datetime.datetime.now() - last_updated).total_seconds() < max_age_hours * 3600:
                        df = pd.read_sql(f'SELECT * FROM {table_name}', conn, index_col='Date')
                        df.index = pd.to_datetime(df.index)
                        return df
        except Exception:
            pass
        return None

    def save_data(self, ticker: Any, interval: Any, df: Any) -> None:
        """Save data."""
        if df is None or df.empty:
            return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        safe_ticker = ticker.replace('^', 'IDX_').replace('=', 'FX_').replace('/', '_').replace('-', '_')
        table_name = f'cache_{safe_ticker}_{interval}'
        try:
            with sqlite3.connect(self.db_path) as conn:
                save_df = df.copy()
                if save_df.index.name == 'Date' and 'Date' in save_df.columns:
                    save_df.index.name = 'DateIndex'
                save_df.to_sql(table_name, conn, if_exists='replace', index=True)
                conn.execute('INSERT OR REPLACE INTO meta (ticker, interval, last_updated) VALUES (?, ?, ?)', (ticker, interval, datetime.datetime.now().isoformat()))
        except Exception as e:
            logger.warning(f'Failed to save cache for {ticker}: {e}')

    def get_options_expiries(self, ticker: Any, max_age_hours: Any=24) -> Any:
        """Handle get options expiries."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT expirations, last_updated FROM meta_options WHERE ticker=?', (ticker,))
                row = cursor.fetchone()
                if row:
                    exp_json, last_updated_str = row
                    last_updated = datetime.datetime.fromisoformat(last_updated_str)
                    if (datetime.datetime.now() - last_updated).total_seconds() < max_age_hours * 3600:
                        return json.loads(exp_json)
        except Exception:
            pass
        return None

    def save_options_expiries(self, ticker: Any, expiries: Any) -> None:
        """Save options expiries."""
        if not expiries:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('INSERT OR REPLACE INTO meta_options (ticker, expirations, last_updated) VALUES (?, ?, ?)', (ticker, json.dumps(list(expiries)), datetime.datetime.now().isoformat()))
        except Exception as e:
            logger.warning(f'Failed to save options expiries for {ticker}: {e}')

    def get_options_chain(self, ticker: Any, expiry: Any, max_age_minutes: Any=60) -> Any:
        """Handle get options chain."""
        safe_ticker = ticker.replace('^', 'IDX_').replace('=', 'FX_').replace('/', '_').replace('-', '_')
        safe_expiry = expiry.replace('-', '_')
        table_name = f'opt_{safe_ticker}_{safe_expiry}'
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT last_updated FROM meta WHERE ticker=? AND interval=?', (ticker, f'OPT_{expiry}'))
                row = cursor.fetchone()
                if row:
                    last_updated = datetime.datetime.fromisoformat(row[0])
                    if (datetime.datetime.now() - last_updated).total_seconds() < max_age_minutes * 60:
                        df = pd.read_sql(f'SELECT * FROM {table_name}', conn)
                        return df
        except Exception:
            pass
        return None

    def save_options_chain(self, ticker: Any, expiry: Any, df: Any) -> None:
        """Save options chain."""
        if df is None or df.empty:
            return
        safe_ticker = ticker.replace('^', 'IDX_').replace('=', 'FX_').replace('/', '_').replace('-', '_')
        safe_expiry = expiry.replace('-', '_')
        table_name = f'opt_{safe_ticker}_{safe_expiry}'
        try:
            with sqlite3.connect(self.db_path) as conn:
                df.to_sql(table_name, conn, if_exists='replace', index=False)
                conn.execute('INSERT OR REPLACE INTO meta (ticker, interval, last_updated) VALUES (?, ?, ?)', (ticker, f'OPT_{expiry}', datetime.datetime.now().isoformat()))
        except Exception as e:
            logger.warning(f'Failed to save options chain for {ticker}: {e}')
