from __future__ import annotations
import datetime
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from .dependencies import logger, pd
from .paths import user_data_path

class CacheManager:
    _CACHE_META_TABLES = {'meta', 'meta_options'}
    _SIMPLE_IDENTIFIER_PART = re.compile(r'^[A-Za-z0-9_]+$')
    _SAFE_IDENTIFIER_CHARS = re.compile(r'[^A-Za-z0-9_]+')

    def __init__(self, db_path: Any=None) -> None:
        """Initialize the object."""
        self.db_path = str(user_data_path('budget_cache.db')) if db_path is None else str(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Handle init db."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('\n                    CREATE TABLE IF NOT EXISTS meta (\n                        ticker TEXT,\n                        interval TEXT,\n                        last_updated TIMESTAMP,\n                        PRIMARY KEY (ticker, interval)\n                    )\n                ')
                conn.execute('\n                    CREATE TABLE IF NOT EXISTS meta_options (\n                        ticker TEXT PRIMARY KEY,\n                        expirations TEXT,\n                        last_updated TIMESTAMP\n                    )\n                ')
        except Exception as e:
            logger.error(f'Failed to initialize cache DB: {e}')

    def _cache_artifact_paths(self) -> Any:
        """Return the main cache DB path and any SQLite sidecar files."""
        db_path = Path(self.db_path)
        return [
            db_path,
            Path(f'{self.db_path}-journal'),
            Path(f'{self.db_path}-wal'),
            Path(f'{self.db_path}-shm'),
        ]

    def _connect(self) -> Any:
        """Open a SQLite connection with a small busy timeout."""
        return sqlite3.connect(self.db_path, timeout=2.0)

    def _sqlite_identifier_part(self, value: Any) -> str:
        """Return a collision-resistant SQLite-safe segment for cache tables."""
        raw = str(value or '').strip()
        if self._SIMPLE_IDENTIFIER_PART.fullmatch(raw):
            return raw or 'blank'
        legacy = raw.replace('^', 'IDX_').replace('=', 'FX_').replace('/', '_').replace('-', '_')
        sanitized = self._SAFE_IDENTIFIER_CHARS.sub('_', legacy).strip('_') or 'blank'
        digest = hashlib.sha1(raw.encode('utf-8', errors='ignore')).hexdigest()[:10]
        return f'{sanitized[:48]}_{digest}'

    def _cache_table_name(self, prefix: str, *parts: Any) -> str:
        """Build a SQLite-safe cache table name while preserving simple legacy names."""
        return '_'.join([str(prefix), *(self._sqlite_identifier_part(part) for part in parts)])

    def _quote_identifier(self, identifier: Any) -> str:
        """Quote a SQLite identifier for direct SQL statements."""
        return '"' + str(identifier).replace('"', '""') + '"'

    def _drop_cache_tables(self, conn: Any) -> Any:
        """Remove cached data tables while preserving the cache schema tables."""
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = [str(row[0]) for row in cursor.fetchall() if row and row[0]]
        data_tables = [name for name in table_names if name not in self._CACHE_META_TABLES]
        for table_name in data_tables:
            conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.execute('DELETE FROM meta')
        conn.execute('DELETE FROM meta_options')
        conn.commit()
        return bool(data_tables or table_names)

    def _cleanup_sidecar_files(self) -> Any:
        """Try to remove transient SQLite sidecars without failing the reset."""
        removed = []
        skipped = []
        for path in self._cache_artifact_paths()[1:]:
            if not path.exists():
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except FileNotFoundError:
                continue
            except Exception as exc:
                skipped.append(f'{path.name}: {exc}')
        return removed, skipped

    def clear_all(self) -> Any:
        """Clear all persisted cache data without deleting a live SQLite DB file."""
        db_path = Path(self.db_path)
        existed = any(path.exists() for path in self._cache_artifact_paths())
        attempts = 3
        last_error = None
        for attempt in range(attempts):
            try:
                with self._connect() as conn:
                    conn.execute('PRAGMA busy_timeout = 2000')
                    cleared_any = self._drop_cache_tables(conn)
                self._init_db()
                removed_sidecars, skipped_sidecars = self._cleanup_sidecar_files()
                if removed_sidecars:
                    logger.info('Removed cache sidecar files for %s: %s', db_path, removed_sidecars)
                if skipped_sidecars:
                    logger.info('Skipped removing busy cache sidecars for %s: %s', db_path, skipped_sidecars)
                logger.info('Cleared cache contents for %s on attempt %s.', db_path, attempt + 1)
                return existed or cleared_any
            except sqlite3.OperationalError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise RuntimeError(f'cache is currently in use: {exc}') from exc
            except Exception as exc:
                last_error = exc
                raise RuntimeError(str(exc)) from exc
        if last_error is not None:
            raise RuntimeError(str(last_error))
        return existed

    def _cache_return(self, value: Any, age_seconds: Any, *, return_metadata: bool) -> Any:
        if not return_metadata:
            return value
        return value, {'cache_age_seconds': age_seconds}

    def get_data(self, ticker: Any, interval: Any, max_age_hours: Any=24, *, allow_stale: bool=False, return_metadata: bool=False) -> Any:
        """Handle get data."""
        table_name = self._cache_table_name('cache', ticker, interval)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT last_updated FROM meta WHERE ticker=? AND interval=?', (ticker, interval))
                row = cursor.fetchone()
                if row:
                    last_updated = datetime.datetime.fromisoformat(row[0])
                    age_seconds = (datetime.datetime.now() - last_updated).total_seconds()
                    if allow_stale or age_seconds < max_age_hours * 3600:
                        df = pd.read_sql(f'SELECT * FROM {self._quote_identifier(table_name)}', conn, index_col='Date')
                        df.index = pd.to_datetime(df.index)
                        return self._cache_return(df, age_seconds, return_metadata=return_metadata)
        except Exception as exc:
            logger.debug('Cache read failed for %s %s: %s', ticker, interval, exc)
        return None

    def save_data(self, ticker: Any, interval: Any, df: Any) -> None:
        """Save data."""
        if df is None or df.empty:
            return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        table_name = self._cache_table_name('cache', ticker, interval)
        try:
            with sqlite3.connect(self.db_path) as conn:
                save_df = df.copy()
                if save_df.index.name == 'Date' and 'Date' in save_df.columns:
                    save_df.index.name = 'DateIndex'
                save_df.to_sql(table_name, conn, if_exists='replace', index=True)
                conn.execute('INSERT OR REPLACE INTO meta (ticker, interval, last_updated) VALUES (?, ?, ?)', (ticker, interval, datetime.datetime.now().isoformat()))
        except Exception as e:
            logger.warning(f'Failed to save cache for {ticker}: {e}')

    def get_options_expiries(self, ticker: Any, max_age_hours: Any=24, *, allow_stale: bool=False, return_metadata: bool=False) -> Any:
        """Handle get options expiries."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT expirations, last_updated FROM meta_options WHERE ticker=?', (ticker,))
                row = cursor.fetchone()
                if row:
                    exp_json, last_updated_str = row
                    last_updated = datetime.datetime.fromisoformat(last_updated_str)
                    age_seconds = (datetime.datetime.now() - last_updated).total_seconds()
                    if allow_stale or age_seconds < max_age_hours * 3600:
                        return self._cache_return(json.loads(exp_json), age_seconds, return_metadata=return_metadata)
        except Exception as exc:
            logger.debug('Options expiry cache read failed for %s: %s', ticker, exc)
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

    def get_options_chain(self, ticker: Any, expiry: Any, max_age_minutes: Any=60, *, allow_stale: bool=False, return_metadata: bool=False) -> Any:
        """Handle get options chain."""
        table_name = self._cache_table_name('opt', ticker, expiry)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT last_updated FROM meta WHERE ticker=? AND interval=?', (ticker, f'OPT_{expiry}'))
                row = cursor.fetchone()
                if row:
                    last_updated = datetime.datetime.fromisoformat(row[0])
                    age_seconds = (datetime.datetime.now() - last_updated).total_seconds()
                    if allow_stale or age_seconds < max_age_minutes * 60:
                        df = pd.read_sql(f'SELECT * FROM {self._quote_identifier(table_name)}', conn)
                        return self._cache_return(df, age_seconds, return_metadata=return_metadata)
        except Exception as exc:
            logger.debug('Options chain cache read failed for %s %s: %s', ticker, expiry, exc)
        return None

    def save_options_chain(self, ticker: Any, expiry: Any, df: Any) -> None:
        """Save options chain."""
        if df is None or df.empty:
            return
        table_name = self._cache_table_name('opt', ticker, expiry)
        try:
            with sqlite3.connect(self.db_path) as conn:
                df.to_sql(table_name, conn, if_exists='replace', index=False)
                conn.execute('INSERT OR REPLACE INTO meta (ticker, interval, last_updated) VALUES (?, ?, ?)', (ticker, f'OPT_{expiry}', datetime.datetime.now().isoformat()))
        except Exception as e:
            logger.warning(f'Failed to save options chain for {ticker}: {e}')
