"""Own and repair the sqlite timezone cache yfinance keeps beside every ticker request.

yfinance 1.5.2 resolves a ticker's exchange timezone before it will return any history, and it
memoizes that lookup in a peewee/sqlite database (``tkr-tz.db``). The lookup is not optional: if the
database raises, the ticker is reported as a failed download. So a single corrupt file turns every
price request in the process into "no data" -- silently, because ``yf.download`` reports the symbol
as failed rather than propagating the sqlite error.

That is not hypothetical. The default location is shared by every yfinance install on the machine,
and this app writes it from many threads at once (``yf.download(..., threads=True)`` fans out) and
from several processes at once (each launch is an independent process). Peewee opens the database
with default journalling and no busy timeout, so concurrent writers collide; the observed failure
modes were ``OperationalError('database is locked')`` under contention and, after enough of it, a
permanent ``DatabaseError('database disk image is malformed')`` that took out roughly 70% of the
holdings on every heatmap and quote page until the file was deleted by hand.

Two fixes, both here:

* Move the cache under the app's own writable directory, so it is not shared with unrelated
  yfinance installs and ``paths`` stays the single authority on where the app writes.
* Verify it on the way in and rebuild it when it is damaged, then open it in WAL mode with a busy
  timeout so concurrent writers wait instead of corrupting. A timezone cache is pure derived data
  -- discarding it costs one lookup per ticker and nothing else -- so repair is always safe.

Deliberately Qt-free, and never raises: losing the cache must degrade to yfinance's own default
behaviour rather than break startup. See ``services/yahoo_rate_limit.py`` for the sibling gate that
installs at the same lazy-load seam.
"""
from __future__ import annotations

import os
import sqlite3
import threading

from ..paths import user_data_path

#: Directory name under the app's user-data dir. yfinance appends its own file names.
TZ_CACHE_DIR_NAME = 'yfinance-cache'
#: The database yfinance keeps the per-ticker timezone map in.
TZ_CACHE_DB_NAME = 'tkr-tz.db'
#: Milliseconds a blocked writer waits for the lock before giving up. Comfortably longer than any
#: single timezone write, so thread and process contention resolves by waiting.
DEFAULT_BUSY_TIMEOUT_MS = 5000

_INSTALL_LOCK = threading.Lock()
_installed = False
_cache_dir = ''


def is_installed() -> bool:
    return _installed


def cache_dir() -> str:
    """Return the directory handed to yfinance, or an empty string when never installed."""
    return _cache_dir


def _is_disabled() -> bool:
    return str(os.environ.get('BUDGET_TERMINAL_YF_TZ_CACHE', '1')).strip().lower() in ('0', 'false', 'no')


def _busy_timeout_ms() -> int:
    raw = os.environ.get('BUDGET_TERMINAL_YF_TZ_BUSY_TIMEOUT_MS')
    if raw is None:
        return DEFAULT_BUSY_TIMEOUT_MS
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return DEFAULT_BUSY_TIMEOUT_MS


def database_is_sound(db_path: str) -> bool:
    """Return whether the timezone database opens and passes sqlite's own integrity check.

    A missing file counts as sound: yfinance creates it on first use.
    """
    if not os.path.isfile(db_path):
        return True
    connection = None
    try:
        connection = sqlite3.connect(db_path, timeout=5.0)
        rows = connection.execute('PRAGMA integrity_check').fetchall()
    except sqlite3.Error:
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
    return bool(rows) and str(rows[0][0]).strip().lower() == 'ok'


def discard_database(db_path: str) -> bool:
    """Delete the timezone database and its journal siblings. Returns whether anything was removed.

    The ``-wal`` and ``-shm`` files must go too: leaving a stale WAL beside a fresh database is
    itself a corruption source, and the observed bad state had a 148KB WAL against a 64KB database.
    """
    removed = False
    for suffix in ('', '-wal', '-shm', '-journal'):
        target = db_path + suffix
        try:
            if os.path.isfile(target):
                os.remove(target)
                removed = True
        except OSError:
            # A file held open by another process stays put; yfinance then falls back to its own
            # behaviour rather than the app failing to start.
            continue
    return removed


def harden_database(db_path: str, *, busy_timeout_ms: int | None = None) -> bool:
    """Put the timezone database into WAL mode with a busy timeout so writers wait, not collide.

    Applied to the file rather than to peewee's connection because yfinance owns that connection.
    ``journal_mode`` is a persistent property of the database, so setting it here carries over.
    """
    timeout_ms = _busy_timeout_ms() if busy_timeout_ms is None else max(0, int(busy_timeout_ms))
    connection = None
    try:
        connection = sqlite3.connect(db_path, timeout=5.0)
        connection.execute('PRAGMA busy_timeout = ' + str(timeout_ms))
        connection.execute('PRAGMA journal_mode = WAL')
        connection.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass


def prepare_cache_dir(directory: str, *, busy_timeout_ms: int | None = None) -> str:
    """Verify, repairing if needed, the timezone database inside ``directory``.

    Returns the directory so callers can chain. Safe to call repeatedly.
    """
    from ..dependencies import logger

    os.makedirs(directory, exist_ok=True)
    db_path = os.path.join(directory, TZ_CACHE_DB_NAME)
    if not database_is_sound(db_path):
        logger.warning(
            'yfinance timezone cache at %s is corrupt; rebuilding it. '
            'Every ticker would otherwise report as a failed download.',
            db_path,
        )
        discard_database(db_path)
    harden_database(db_path, busy_timeout_ms=busy_timeout_ms)
    return directory


def install_yahoo_tz_cache(*, force: bool = False) -> bool:
    """Point yfinance at an app-owned timezone cache, repairing it first when damaged.

    Imports yfinance, so call it from the lazy-load hook in ``dependencies`` rather than at startup,
    for the same reason as ``install_yahoo_rate_limit``. Must run before the first request goes out.
    Returns whether the relocation happened. Never raises.

    Set ``BUDGET_TERMINAL_YF_TZ_CACHE=0`` to leave yfinance on its default location.
    """
    global _installed, _cache_dir
    if _installed and not force:
        return True
    if _is_disabled():
        return False
    with _INSTALL_LOCK:
        if _installed and not force:
            return True
        try:
            import yfinance as yf

            directory = str(user_data_path(TZ_CACHE_DIR_NAME))
            prepare_cache_dir(directory)
            yf.set_tz_cache_location(directory)
            _cache_dir = directory
            _installed = True
            return True
        except Exception:
            return False


def repair_installed_cache() -> bool:
    """Re-verify the cache already handed to yfinance, rebuilding it if it has since gone bad.

    Exposed for a recovery path: corruption can appear mid-session, and the symptom -- every symbol
    failing at once -- is recoverable without a restart once the file is replaced.
    """
    directory = _cache_dir
    if not directory:
        return False
    try:
        prepare_cache_dir(directory)
        return True
    except Exception:
        return False
