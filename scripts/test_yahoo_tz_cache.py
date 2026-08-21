"""Smoke tests for the yfinance timezone cache repair.

The bug this guards: a corrupt ``tkr-tz.db`` makes yfinance report *every* ticker as a failed
download, because it resolves a ticker's timezone through that database before returning history.
Observed live, it cut heatmap quote coverage to 147/503 (SPY), 31/102 (QQQ) and 12/30 (DIA) while
looking like an ordinary partial load. Repairing the file restored all three to full coverage.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.services import yahoo_tz_cache as tz


def _corrupt_db(directory: str) -> str:
    """Write a file that is definitely not a valid sqlite database."""
    db_path = os.path.join(directory, tz.TZ_CACHE_DB_NAME)
    with open(db_path, 'wb') as handle:
        handle.write(b'SQLite format 3\x00' + os.urandom(4096))
    return db_path


def _valid_db(directory: str) -> str:
    db_path = os.path.join(directory, tz.TZ_CACHE_DB_NAME)
    connection = sqlite3.connect(db_path)
    connection.execute('CREATE TABLE IF NOT EXISTS _kv (key TEXT PRIMARY KEY, value TEXT)')
    connection.execute("INSERT OR REPLACE INTO _kv VALUES ('AAPL', 'America/New_York')")
    connection.commit()
    connection.close()
    return db_path


def test_missing_database_counts_as_sound() -> None:
    with tempfile.TemporaryDirectory() as directory:
        assert tz.database_is_sound(os.path.join(directory, tz.TZ_CACHE_DB_NAME))


def test_corrupt_database_is_detected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        assert not tz.database_is_sound(_corrupt_db(directory))


def test_valid_database_passes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        assert tz.database_is_sound(_valid_db(directory))


def test_prepare_rebuilds_a_corrupt_database() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db_path = _corrupt_db(directory)
        # A stale oversized WAL beside the database is part of the bad state and must go too.
        for suffix in ('-wal', '-shm'):
            with open(db_path + suffix, 'wb') as handle:
                handle.write(os.urandom(2048))

        tz.prepare_cache_dir(directory)

        assert tz.database_is_sound(db_path), 'corrupt database should have been rebuilt'
        assert not os.path.isfile(db_path + '-shm'), 'stale shm should have been discarded'


def test_prepare_preserves_a_healthy_database() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db_path = _valid_db(directory)

        tz.prepare_cache_dir(directory)

        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute("SELECT value FROM _kv WHERE key = 'AAPL'").fetchall()
        finally:
            connection.close()
        assert rows == [('America/New_York',)], 'a sound cache must not be thrown away'


def test_prepare_sets_wal_and_busy_timeout() -> None:
    """WAL plus a busy timeout is what stops concurrent writers corrupting the file again."""
    with tempfile.TemporaryDirectory() as directory:
        db_path = _valid_db(directory)
        tz.prepare_cache_dir(directory, busy_timeout_ms=4321)

        connection = sqlite3.connect(db_path)
        try:
            mode = connection.execute('PRAGMA journal_mode').fetchone()[0]
        finally:
            connection.close()
        assert str(mode).lower() == 'wal', f'expected WAL journalling, got {mode!r}'


def test_prepare_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        _corrupt_db(directory)
        tz.prepare_cache_dir(directory)
        tz.prepare_cache_dir(directory)
        assert tz.database_is_sound(os.path.join(directory, tz.TZ_CACHE_DB_NAME))


def test_prepare_creates_a_missing_directory() -> None:
    with tempfile.TemporaryDirectory() as parent:
        directory = os.path.join(parent, 'nested', tz.TZ_CACHE_DIR_NAME)
        tz.prepare_cache_dir(directory)
        assert os.path.isdir(directory)


def test_env_var_opts_out() -> None:
    previous = os.environ.get('BUDGET_TERMINAL_YF_TZ_CACHE')
    os.environ['BUDGET_TERMINAL_YF_TZ_CACHE'] = '0'
    try:
        assert tz.install_yahoo_tz_cache(force=True) is False
    finally:
        if previous is None:
            os.environ.pop('BUDGET_TERMINAL_YF_TZ_CACHE', None)
        else:
            os.environ['BUDGET_TERMINAL_YF_TZ_CACHE'] = previous


def test_install_points_yfinance_at_the_app_owned_directory() -> None:
    assert tz.install_yahoo_tz_cache(force=True), 'install should succeed with yfinance available'
    assert tz.is_installed()
    directory = tz.cache_dir()
    assert directory and os.path.isdir(directory)
    assert directory.endswith(tz.TZ_CACHE_DIR_NAME), 'cache must live under the app user-data dir'

    import yfinance as yf
    from yfinance import cache as yf_cache

    assert yf is not None
    assert os.path.normcase(yf_cache._TzDBManager.get_location()) == os.path.normcase(directory)


def test_lazy_proxy_installs_the_tz_cache_on_first_yfinance_use() -> None:
    """The proxy's on_load hook is the only point that is both lazy and before the first request."""
    from budget_terminal_app.dependencies import yf

    _ = yf.Ticker
    assert tz.is_installed()
    assert tz.cache_dir()


if __name__ == '__main__':
    test_missing_database_counts_as_sound()
    test_corrupt_database_is_detected()
    test_valid_database_passes()
    test_prepare_rebuilds_a_corrupt_database()
    test_prepare_preserves_a_healthy_database()
    test_prepare_sets_wal_and_busy_timeout()
    test_prepare_is_idempotent()
    test_prepare_creates_a_missing_directory()
    test_env_var_opts_out()
    test_install_points_yfinance_at_the_app_owned_directory()
    test_lazy_proxy_installs_the_tz_cache_on_first_yfinance_use()
    print('yahoo tz cache smoke tests passed')
