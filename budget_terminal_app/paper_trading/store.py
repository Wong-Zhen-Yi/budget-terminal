from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from budget_terminal_app.paths import user_data_path

from .models import (
    AccountStatus,
    CashEventType,
    OrderStatus,
    PaperOrderRequest,
    PaperQuote,
    RecurringRunStatus,
    RecurringScheduleSpec,
    RecurringStatus,
    iso_utc,
)


PAPER_DATABASE_VERSION = 4
PAPER_BACKUP_VERSION = 4
SUPPORTED_PAPER_BACKUP_VERSIONS = {1, 2, 3, PAPER_BACKUP_VERSION}
PAPER_DATABASE_FILE = user_data_path("paper_trading.db")
PAPER_ROLLBACK_DIR = user_data_path("backups", "paper_trading")

_TABLES = (
    "accounts",
    "recurring_schedules",
    "orders",
    "order_events",
    "fills",
    "cash_events",
    "positions",
    "journal_entries",
    "equity_snapshots",
    "recurring_runs",
)


class _ClosingConnection(sqlite3.Connection):
    """Commit or roll back a context-managed connection, then release its file handle."""

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class PaperTradingStore:
    """Transactional SQLite persistence for isolated paper accounts."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or PAPER_DATABASE_FILE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._maintenance_lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._maintenance_lock, self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > PAPER_DATABASE_VERSION:
                raise RuntimeError(
                    f"Paper database version {version} is newer than supported version {PAPER_DATABASE_VERSION}."
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE,
                    initial_cash REAL NOT NULL CHECK (initial_cash > 0),
                    currency TEXT NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
                    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
                    slippage_bps REAL NOT NULL DEFAULT 5 CHECK (slippage_bps >= 0),
                    commission_per_fill REAL NOT NULL DEFAULT 0 CHECK (commission_per_fill >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_active_name
                    ON accounts(name) WHERE status = 'active';

                CREATE TABLE IF NOT EXISTS recurring_schedules (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK (kind IN ('funding', 'buy')),
                    cadence TEXT NOT NULL CHECK (cadence IN ('daily', 'weekly', 'monthly')),
                    amount REAL NOT NULL CHECK (amount >= 0.01),
                    symbol TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT 'LOCAL',
                    local_time TEXT NOT NULL,
                    weekday INTEGER CHECK (weekday IS NULL OR (weekday >= 0 AND weekday <= 6)),
                    month_day INTEGER CHECK (month_day IS NULL OR (month_day >= 1 AND month_day <= 31)),
                    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'cancelled')),
                    pause_reason TEXT NOT NULL DEFAULT '',
                    next_run_at TEXT NOT NULL,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recurring_schedules_due
                    ON recurring_schedules(status, next_run_at, kind);
                CREATE INDEX IF NOT EXISTS idx_recurring_schedules_account
                    ON recurring_schedules(account_id, status, created_at);

                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
                    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit', 'stop')),
                    tif TEXT NOT NULL CHECK (tif IN ('day', 'gtc')),
                    execution_session TEXT NOT NULL DEFAULT 'regular'
                        CHECK (execution_session IN ('regular', 'extended')),
                    quantity REAL NOT NULL CHECK (quantity > 0),
                    filled_quantity REAL NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0 AND filled_quantity <= quantity),
                    limit_price REAL,
                    stop_price REAL,
                    slippage_bps REAL NOT NULL CHECK (slippage_bps >= 0),
                    commission_per_fill REAL NOT NULL CHECK (commission_per_fill >= 0),
                    reserved_cash REAL NOT NULL DEFAULT 0 CHECK (reserved_cash >= 0),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'filled', 'cancelled', 'rejected', 'expired')),
                    rejection_reason TEXT NOT NULL DEFAULT '',
                    last_evaluation TEXT NOT NULL DEFAULT '',
                    submitted_at TEXT NOT NULL,
                    expires_at TEXT,
                    triggered_at TEXT,
                    terminal_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_orders_pending_symbol
                    ON orders(status, symbol, submitted_at);
                CREATE INDEX IF NOT EXISTS idx_orders_account_time
                    ON orders(account_id, submitted_at DESC);

                CREATE TABLE IF NOT EXISTS order_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    prior_status TEXT,
                    new_status TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fills (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
                    quantity REAL NOT NULL CHECK (quantity > 0),
                    quote_bid REAL NOT NULL,
                    quote_ask REAL NOT NULL,
                    reference_price REAL NOT NULL,
                    fill_price REAL NOT NULL CHECK (fill_price > 0),
                    slippage_bps REAL NOT NULL,
                    commission REAL NOT NULL,
                    realized_pnl_delta REAL NOT NULL DEFAULT 0,
                    quote_source TEXT NOT NULL,
                    quote_timestamp TEXT NOT NULL,
                    filled_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fills_account_time
                    ON fills(account_id, filled_at DESC);

                CREATE TABLE IF NOT EXISTS cash_events (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    fill_id TEXT UNIQUE REFERENCES fills(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL
                        CHECK (event_type IN ('initial_deposit', 'deposit', 'withdrawal', 'trade')),
                    amount REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cash_events_account_time
                    ON cash_events(account_id, created_at);

                CREATE TABLE IF NOT EXISTS positions (
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                    average_cost REAL NOT NULL DEFAULT 0 CHECK (average_cost >= 0),
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    mark_price REAL,
                    mark_source TEXT NOT NULL DEFAULT '',
                    mark_timestamp TEXT,
                    mark_is_stale INTEGER NOT NULL DEFAULT 1 CHECK (mark_is_stale IN (0, 1)),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, symbol)
                );

                CREATE TABLE IF NOT EXISTS journal_entries (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
                    fill_id TEXT REFERENCES fills(id) ON DELETE SET NULL,
                    note TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_journal_account_time
                    ON journal_entries(account_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    cash REAL NOT NULL,
                    market_value REAL NOT NULL,
                    equity REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    stale_mark_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_equity_account_time
                    ON equity_snapshots(account_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS recurring_runs (
                    id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL REFERENCES recurring_schedules(id) ON DELETE CASCADE,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    scheduled_for TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'skipped', 'failed')),
                    amount REAL NOT NULL,
                    quantity REAL,
                    reference_price REAL,
                    cash_event_id TEXT REFERENCES cash_events(id) ON DELETE SET NULL,
                    order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
                    message TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(schedule_id, scheduled_for)
                );
                CREATE INDEX IF NOT EXISTS idx_recurring_runs_schedule_time
                    ON recurring_runs(schedule_id, scheduled_for DESC);
                """
            )
            order_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(orders)").fetchall()
            }
            if "execution_session" not in order_columns:
                connection.execute(
                    """ALTER TABLE orders ADD COLUMN execution_session TEXT NOT NULL DEFAULT 'regular'
                       CHECK (execution_session IN ('regular', 'extended'))"""
                )
            if version < 3:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """CREATE TABLE cash_events_v3 (
                           id TEXT PRIMARY KEY,
                           account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                           fill_id TEXT UNIQUE REFERENCES fills(id) ON DELETE CASCADE,
                           event_type TEXT NOT NULL
                               CHECK (event_type IN ('initial_deposit', 'deposit', 'withdrawal', 'trade')),
                           amount REAL NOT NULL,
                           created_at TEXT NOT NULL
                       )"""
                )
                connection.execute(
                    """INSERT INTO cash_events_v3
                       (id, account_id, fill_id, event_type, amount, created_at)
                       SELECT id, account_id, fill_id, event_type, amount, created_at
                       FROM cash_events"""
                )
                connection.execute("DROP TABLE cash_events")
                connection.execute("ALTER TABLE cash_events_v3 RENAME TO cash_events")
                connection.execute(
                    """CREATE INDEX idx_cash_events_account_time
                       ON cash_events(account_id, created_at)"""
                )
            connection.execute(f"PRAGMA user_version = {PAPER_DATABASE_VERSION}")

    @staticmethod
    def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
        return [dict(row) for row in cursor.fetchall()]

    def create_account(
        self,
        name: str,
        initial_cash: float,
        *,
        slippage_bps: float = 5.0,
        commission_per_fill: float = 0.0,
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()[:80]
        if not clean_name:
            raise ValueError("Account name is required.")
        cash = _positive_finite(initial_cash, "Starting cash")
        slippage = _nonnegative_finite(slippage_bps, "Slippage")
        commission = _nonnegative_finite(commission_per_fill, "Commission")
        now = iso_utc()
        account_id = str(uuid.uuid4())
        with self._connect() as connection:
            account_count = int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
            if account_count >= 5:
                raise ValueError("Paper trading supports up to five accounts, including archived accounts.")
            try:
                connection.execute(
                    """INSERT INTO accounts
                       (id, name, initial_cash, currency, status, slippage_bps, commission_per_fill, created_at, updated_at)
                       VALUES (?, ?, ?, 'USD', 'active', ?, ?, ?, ?)""",
                    (account_id, clean_name, cash, slippage, commission, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"An active paper account named {clean_name!r} already exists.") from exc
            connection.execute(
                """INSERT INTO cash_events (id, account_id, fill_id, event_type, amount, created_at)
                   VALUES (?, ?, NULL, ?, ?, ?)""",
                (str(uuid.uuid4()), account_id, CashEventType.INITIAL_DEPOSIT, cash, now),
            )
        return self.get_account(account_id)

    def list_accounts(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM accounts"
        params: tuple[Any, ...] = ()
        if not include_archived:
            sql += " WHERE status = ?"
            params = (AccountStatus.ACTIVE,)
        sql += " ORDER BY status, created_at, name"
        with self._connect() as connection:
            return self._rows(connection.execute(sql, params))

    def get_account(self, account_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            raise ValueError("Paper account was not found.")
        return dict(row)

    def update_account(
        self,
        account_id: str,
        *,
        name: str | None = None,
        initial_cash: float | None = None,
        target_cash: float | None = None,
        slippage_bps: float | None = None,
        commission_per_fill: float | None = None,
    ) -> dict[str, Any]:
        if initial_cash is not None and target_cash is not None:
            raise ValueError("Choose either starting cash or a target cash balance, not both.")
        with self._maintenance_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                raise ValueError("Paper account was not found.")
            account = dict(row)
            clean_name = str(name if name is not None else account["name"]).strip()[:80]
            if not clean_name:
                raise ValueError("Account name is required.")
            slippage = _nonnegative_finite(
                account["slippage_bps"] if slippage_bps is None else slippage_bps,
                "Slippage",
            )
            commission = _nonnegative_finite(
                account["commission_per_fill"] if commission_per_fill is None else commission_per_fill,
                "Commission",
            )
            starting_cash = _positive_finite(
                account["initial_cash"] if initial_cash is None else initial_cash,
                "Starting cash",
            )
            order_count = int(
                connection.execute("SELECT COUNT(*) FROM orders WHERE account_id = ?", (account_id,)).fetchone()[0]
            )
            if order_count and abs(starting_cash - float(account["initial_cash"])) > 1e-7:
                raise ValueError("Starting cash cannot change after the first order is submitted.")
            current_cash = self.cash_balance(account_id, connection=connection)
            cash_delta = 0.0
            if target_cash is not None:
                desired_cash = _nonnegative_finite(target_cash, "Cash balance")
                if desired_cash > 1_000_000_000:
                    raise ValueError("Cash balance cannot exceed $1,000,000,000.00.")
                reserved = self.reserved_cash(account_id, connection=connection)
                if desired_cash + 1e-7 < reserved:
                    raise ValueError(f"Cash balance cannot be below ${reserved:,.2f} reserved for pending buy orders.")
                cash_delta = round(desired_cash - current_cash, 6)
                if account["status"] == AccountStatus.ARCHIVED and abs(cash_delta) > 1e-7:
                    raise ValueError("Restore the account before changing its cash balance.")
                if not order_count and desired_cash > 0:
                    starting_cash = desired_cash
            try:
                connection.execute(
                    """UPDATE accounts
                       SET name = ?, initial_cash = ?, slippage_bps = ?, commission_per_fill = ?, updated_at = ?
                       WHERE id = ?""",
                    (clean_name, starting_cash, slippage, commission, iso_utc(), account_id),
                )
                if initial_cash is not None or (target_cash is not None and not order_count and target_cash > 0):
                    connection.execute(
                        """UPDATE cash_events SET amount = ?
                           WHERE account_id = ? AND event_type = 'initial_deposit'""",
                        (starting_cash, account_id),
                    )
                    if not order_count:
                        starting_cash_delta = starting_cash - current_cash
                        connection.execute(
                            """UPDATE equity_snapshots
                               SET cash = cash + ?, equity = equity + ?
                               WHERE account_id = ?""",
                            (starting_cash_delta, starting_cash_delta, account_id),
                        )
                elif target_cash is not None and abs(cash_delta) > 1e-7:
                    event_type = CashEventType.DEPOSIT if cash_delta > 0 else CashEventType.WITHDRAWAL
                    connection.execute(
                        """INSERT INTO cash_events (id, account_id, fill_id, event_type, amount, created_at)
                           VALUES (?, ?, NULL, ?, ?, ?)""",
                        (str(uuid.uuid4()), account_id, event_type, cash_delta, iso_utc()),
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"An active paper account named {clean_name!r} already exists.") from exc
        return self.get_account(account_id)

    def can_edit_initial_cash(self, account_id: str) -> bool:
        with self._connect() as connection:
            return not bool(
                connection.execute("SELECT 1 FROM orders WHERE account_id = ? LIMIT 1", (account_id,)).fetchone()
            )

    def create_recurring_schedule(
        self,
        spec: RecurringScheduleSpec,
        *,
        next_run_at: str,
    ) -> dict[str, Any]:
        normalized = spec.normalized()
        account = self.get_account(normalized.account_id)
        if account["status"] != AccountStatus.ACTIVE:
            raise ValueError("Restore the account before creating a recurring schedule.")
        now = iso_utc()
        schedule_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO recurring_schedules
                   (id, account_id, kind, cadence, amount, symbol, timezone, local_time,
                    weekday, month_day, status, pause_reason, next_run_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', '', ?, ?, ?)""",
                (
                    schedule_id,
                    normalized.account_id,
                    normalized.kind,
                    normalized.cadence,
                    normalized.amount,
                    normalized.symbol,
                    normalized.timezone,
                    normalized.local_time,
                    normalized.weekday,
                    normalized.month_day,
                    str(next_run_at),
                    now,
                    now,
                ),
            )
        return self.get_recurring_schedule(schedule_id)

    def update_recurring_schedule(
        self,
        schedule_id: str,
        spec: RecurringScheduleSpec,
        *,
        next_run_at: str,
    ) -> dict[str, Any]:
        normalized = spec.normalized()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT account_id, status FROM recurring_schedules WHERE id = ?",
                (schedule_id,),
            ).fetchone()
            if existing is None:
                raise ValueError("Recurring schedule was not found.")
            if existing["status"] == RecurringStatus.CANCELLED:
                raise ValueError("Cancelled recurring schedules cannot be edited.")
            if str(existing["account_id"]) != normalized.account_id:
                raise ValueError("A recurring schedule cannot move to another account.")
            connection.execute(
                """UPDATE recurring_schedules
                   SET kind = ?, cadence = ?, amount = ?, symbol = ?, timezone = ?, local_time = ?,
                       weekday = ?, month_day = ?, next_run_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    normalized.kind,
                    normalized.cadence,
                    normalized.amount,
                    normalized.symbol,
                    normalized.timezone,
                    normalized.local_time,
                    normalized.weekday,
                    normalized.month_day,
                    str(next_run_at),
                    iso_utc(),
                    schedule_id,
                ),
            )
        return self.get_recurring_schedule(schedule_id)

    def get_recurring_schedule(self, schedule_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM recurring_schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            raise ValueError("Recurring schedule was not found.")
        return dict(row)

    def list_recurring_schedules(
        self,
        account_id: str,
        *,
        include_cancelled: bool = True,
    ) -> list[dict[str, Any]]:
        sql = """SELECT schedule.*,
                        (SELECT status FROM recurring_runs run
                         WHERE run.schedule_id = schedule.id
                         ORDER BY run.scheduled_for DESC LIMIT 1) AS last_run_status,
                        (SELECT message FROM recurring_runs run
                         WHERE run.schedule_id = schedule.id
                         ORDER BY run.scheduled_for DESC LIMIT 1) AS last_run_message
                 FROM recurring_schedules schedule WHERE schedule.account_id = ?"""
        params: list[Any] = [account_id]
        if not include_cancelled:
            sql += " AND schedule.status <> 'cancelled'"
        sql += " ORDER BY schedule.status, schedule.created_at, schedule.id"
        with self._connect() as connection:
            return self._rows(connection.execute(sql, tuple(params)))

    def set_recurring_schedule_status(
        self,
        schedule_id: str,
        status: RecurringStatus | str,
        *,
        next_run_at: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        normalized_status = RecurringStatus(str(status))
        schedule = self.get_recurring_schedule(schedule_id)
        if schedule["status"] == RecurringStatus.CANCELLED and normalized_status != RecurringStatus.CANCELLED:
            raise ValueError("Cancelled recurring schedules cannot be resumed.")
        if normalized_status == RecurringStatus.ACTIVE and not next_run_at:
            raise ValueError("A resumed schedule needs a future run time.")
        if normalized_status == RecurringStatus.ACTIVE:
            account = self.get_account(str(schedule["account_id"]))
            if account["status"] != AccountStatus.ACTIVE:
                raise ValueError("Restore the account before resuming its recurring schedule.")
        with self._connect() as connection:
            connection.execute(
                """UPDATE recurring_schedules
                   SET status = ?, pause_reason = ?, next_run_at = COALESCE(?, next_run_at), updated_at = ?
                   WHERE id = ?""",
                (
                    normalized_status,
                    str(reason or "")[:250] if normalized_status == RecurringStatus.PAUSED else "",
                    str(next_run_at) if next_run_at else None,
                    iso_utc(),
                    schedule_id,
                ),
            )
        return self.get_recurring_schedule(schedule_id)

    def due_recurring_schedules(self, now: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._rows(
                connection.execute(
                    """SELECT schedule.* FROM recurring_schedules schedule
                       JOIN accounts account ON account.id = schedule.account_id
                       WHERE schedule.status = 'active' AND account.status = 'active'
                         AND schedule.next_run_at <= ?
                       ORDER BY CASE schedule.kind WHEN 'funding' THEN 0 ELSE 1 END,
                                schedule.next_run_at, schedule.created_at""",
                    (str(now),),
                )
            )

    def claim_recurring_run(
        self,
        schedule_id: str,
        *,
        scheduled_for: str,
        next_run_at: str,
        started_at: str,
    ) -> dict[str, Any] | None:
        run_id = str(uuid.uuid4())
        with self._maintenance_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            schedule = connection.execute(
                """SELECT schedule.* FROM recurring_schedules schedule
                   JOIN accounts account ON account.id = schedule.account_id
                   WHERE schedule.id = ? AND schedule.status = 'active' AND account.status = 'active'""",
                (schedule_id,),
            ).fetchone()
            if schedule is None or str(schedule["next_run_at"]) > str(started_at):
                return None
            try:
                connection.execute(
                    """INSERT INTO recurring_runs
                       (id, schedule_id, account_id, scheduled_for, status, amount, message, started_at)
                       VALUES (?, ?, ?, ?, 'running', ?, '', ?)""",
                    (run_id, schedule_id, schedule["account_id"], scheduled_for, schedule["amount"], started_at),
                )
            except sqlite3.IntegrityError:
                return None
            connection.execute(
                """UPDATE recurring_schedules
                   SET next_run_at = ?, last_run_at = ?, updated_at = ? WHERE id = ?""",
                (next_run_at, scheduled_for, started_at, schedule_id),
            )
            row = connection.execute("SELECT * FROM recurring_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row)

    def complete_recurring_run(
        self,
        run_id: str,
        status: RecurringRunStatus | str,
        *,
        message: str,
        quantity: float | None = None,
        reference_price: float | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_status = RecurringRunStatus(str(status))
        if normalized_status == RecurringRunStatus.RUNNING:
            raise ValueError("A completed recurring run needs a terminal status.")
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE recurring_runs
                   SET status = ?, message = ?, quantity = ?, reference_price = ?, completed_at = ?
                   WHERE id = ? AND status = 'running'""",
                (
                    normalized_status,
                    str(message or "")[:500],
                    quantity,
                    reference_price,
                    completed_at or iso_utc(),
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Recurring run is no longer pending completion.")
            row = connection.execute("SELECT * FROM recurring_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row)

    def apply_scheduled_funding(self, run_id: str, *, completed_at: str | None = None) -> dict[str, Any]:
        timestamp = completed_at or iso_utc()
        with self._maintenance_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT run.*, schedule.kind, account.status AS account_status
                   FROM recurring_runs run
                   JOIN recurring_schedules schedule ON schedule.id = run.schedule_id
                   JOIN accounts account ON account.id = run.account_id
                   WHERE run.id = ? AND run.status = 'running'""",
                (run_id,),
            ).fetchone()
            if row is None or row["kind"] != "funding":
                raise ValueError("Recurring funding run was not found.")
            if row["account_status"] != AccountStatus.ACTIVE:
                raise ValueError("Archived accounts cannot receive recurring funding.")
            amount = float(row["amount"])
            current_cash = self.cash_balance(str(row["account_id"]), connection=connection)
            if current_cash + amount > 1_000_000_000 + 1e-7:
                raise ValueError("Recurring funding would exceed the $1,000,000,000.00 cash limit.")
            event_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO cash_events (id, account_id, fill_id, event_type, amount, created_at)
                   VALUES (?, ?, NULL, 'deposit', ?, ?)""",
                (event_id, row["account_id"], amount, timestamp),
            )
            connection.execute(
                """UPDATE recurring_runs
                   SET status = 'success', cash_event_id = ?, message = ?, completed_at = ?
                   WHERE id = ?""",
                (event_id, f"Deposited ${amount:,.2f}.", timestamp, run_id),
            )
            event = connection.execute("SELECT * FROM cash_events WHERE id = ?", (event_id,)).fetchone()
        return dict(event)

    def list_recurring_runs(self, schedule_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._rows(
                connection.execute(
                    """SELECT * FROM recurring_runs WHERE schedule_id = ?
                       ORDER BY scheduled_for DESC LIMIT ?""",
                    (schedule_id, max(1, int(limit))),
                )
            )

    def archive_account(self, account_id: str) -> None:
        now = iso_utc()
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                raise ValueError("Paper account was not found.")
            if row["status"] == AccountStatus.ARCHIVED:
                return
            pending = connection.execute(
                "SELECT id FROM orders WHERE account_id = ? AND status = 'pending'",
                (account_id,),
            ).fetchall()
            for order in pending:
                self._transition_order(
                    connection,
                    order["id"],
                    OrderStatus.CANCELLED,
                    "account_archived",
                    "Cancelled because the account was archived.",
                    now,
                )
            connection.execute(
                "UPDATE accounts SET status = 'archived', updated_at = ? WHERE id = ?",
                (now, account_id),
            )
            connection.execute(
                """UPDATE recurring_schedules
                   SET status = 'paused', pause_reason = 'Account archived', updated_at = ?
                   WHERE account_id = ? AND status = 'active'""",
                (now, account_id),
            )

    def restore_account(self, account_id: str) -> None:
        with self._connect() as connection:
            active_count = int(
                connection.execute("SELECT COUNT(*) FROM accounts WHERE status = 'active'").fetchone()[0]
            )
            if active_count >= 5:
                raise ValueError("Paper trading supports up to five active accounts.")
            account = connection.execute("SELECT name FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if account is None:
                raise ValueError("Paper account was not found.")
            try:
                connection.execute(
                    "UPDATE accounts SET status = 'active', updated_at = ? WHERE id = ?",
                    (iso_utc(), account_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Another active account already uses the name {account['name']!r}.") from exc

    def create_order(
        self,
        request: PaperOrderRequest,
        *,
        expires_at: dt.datetime | None,
        reserved_cash: float,
        recurring_run_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = request.normalized()
        account = self.get_account(normalized.account_id)
        if account["status"] != AccountStatus.ACTIVE:
            raise ValueError("Archived accounts cannot place orders.")
        now = iso_utc()
        order_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO orders
                   (id, account_id, symbol, side, order_type, tif, execution_session, quantity, filled_quantity,
                    limit_price, stop_price, slippage_bps, commission_per_fill, reserved_cash,
                    status, submitted_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    order_id,
                    normalized.account_id,
                    normalized.symbol,
                    normalized.side,
                    normalized.order_type,
                    normalized.tif,
                    normalized.execution_session,
                    normalized.quantity,
                    normalized.limit_price,
                    normalized.stop_price,
                    account["slippage_bps"],
                    account["commission_per_fill"],
                    max(float(reserved_cash), 0.0),
                    now,
                    iso_utc(expires_at) if expires_at else None,
                ),
            )
            connection.execute(
                """INSERT INTO order_events
                   (order_id, prior_status, new_status, event_type, message, created_at)
                   VALUES (?, NULL, 'pending', 'submitted', ?, ?)""",
                (
                    order_id,
                    (
                        "Order accepted for pre-market and regular-session evaluation (DAY)."
                        if str(normalized.execution_session) == "extended"
                        else f"Order accepted for regular-session evaluation ({str(normalized.tif).upper()})."
                    ),
                    now,
                ),
            )
            if normalized.reasoning or normalized.tags:
                connection.execute(
                    """INSERT INTO journal_entries
                       (id, account_id, order_id, fill_id, note, tags_json, created_at, updated_at)
                       VALUES (?, ?, ?, NULL, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        normalized.account_id,
                        order_id,
                        normalized.reasoning,
                        json.dumps(list(normalized.tags)),
                        now,
                        now,
                    ),
                )
            if recurring_run_id:
                cursor = connection.execute(
                    """UPDATE recurring_runs SET order_id = ?
                       WHERE id = ? AND account_id = ? AND status = 'running'""",
                    (order_id, recurring_run_id, normalized.account_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("The recurring run is no longer available for this order.")
        return self.get_order(order_id)

    def get_order(self, order_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise ValueError("Paper order was not found.")
        return dict(row)

    def list_orders(
        self,
        account_id: str,
        *,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM orders WHERE account_id = ?"
        params: list[Any] = [account_id]
        if status and status != "all":
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY submitted_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as connection:
            return self._rows(connection.execute(sql, tuple(params)))

    def pending_orders(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._rows(
                connection.execute(
                    """SELECT orders.* FROM orders
                       JOIN accounts ON accounts.id = orders.account_id
                       WHERE orders.status = 'pending' AND accounts.status = 'active'
                       ORDER BY orders.submitted_at"""
                )
            )

    def cancel_order(self, order_id: str, *, message: str = "Cancelled by user.") -> dict[str, Any]:
        now = iso_utc()
        with self._connect() as connection:
            order = connection.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order is None:
                raise ValueError("Paper order was not found.")
            if order["status"] != OrderStatus.PENDING:
                raise ValueError("Only pending orders can be cancelled.")
            self._transition_order(
                connection,
                order_id,
                OrderStatus.CANCELLED,
                "cancelled",
                message,
                now,
            )
        return self.get_order(order_id)

    def expire_order(self, order_id: str, *, message: str) -> None:
        with self._connect() as connection:
            self._transition_order(
                connection,
                order_id,
                OrderStatus.EXPIRED,
                "expired",
                message,
                iso_utc(),
            )

    def reject_order(self, order_id: str, *, reason: str) -> None:
        with self._connect() as connection:
            self._transition_order(
                connection,
                order_id,
                OrderStatus.REJECTED,
                "rejected",
                str(reason),
                iso_utc(),
                rejection_reason=str(reason),
            )

    def update_order_evaluation(self, order_id: str, message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE orders SET last_evaluation = ? WHERE id = ? AND status = 'pending'",
                (str(message or "")[:500], order_id),
            )

    @staticmethod
    def _transition_order(
        connection: sqlite3.Connection,
        order_id: str,
        new_status: OrderStatus | str,
        event_type: str,
        message: str,
        timestamp: str,
        *,
        rejection_reason: str = "",
    ) -> None:
        row = connection.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise ValueError("Paper order was not found.")
        prior = str(row["status"])
        if prior != OrderStatus.PENDING:
            return
        connection.execute(
            """UPDATE orders
               SET status = ?, rejection_reason = ?, last_evaluation = ?, terminal_at = ?
               WHERE id = ?""",
            (str(new_status), rejection_reason, str(message)[:500], timestamp, order_id),
        )
        connection.execute(
            """INSERT INTO order_events
               (order_id, prior_status, new_status, event_type, message, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (order_id, prior, str(new_status), event_type, str(message)[:1000], timestamp),
        )

    def cash_balance(self, account_id: str, *, connection: sqlite3.Connection | None = None) -> float:
        own_connection = connection is None
        database = connection or self._connect()
        try:
            value = database.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM cash_events WHERE account_id = ?",
                (account_id,),
            ).fetchone()[0]
            return float(value or 0.0)
        finally:
            if own_connection:
                database.close()

    def reserved_cash(
        self,
        account_id: str,
        *,
        exclude_order_id: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> float:
        sql = "SELECT COALESCE(SUM(reserved_cash), 0) FROM orders WHERE account_id = ? AND status = 'pending' AND side = 'buy'"
        params: list[Any] = [account_id]
        if exclude_order_id:
            sql += " AND id <> ?"
            params.append(exclude_order_id)
        own_connection = connection is None
        database = connection or self._connect()
        try:
            return float(database.execute(sql, tuple(params)).fetchone()[0] or 0.0)
        finally:
            if own_connection:
                database.close()

    def list_cash_events(self, account_id: str, *, external_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM cash_events WHERE account_id = ?"
        params: list[Any] = [account_id]
        if external_only:
            sql += " AND event_type IN ('initial_deposit', 'deposit', 'withdrawal')"
        sql += " ORDER BY created_at, id"
        with self._connect() as connection:
            return self._rows(connection.execute(sql, tuple(params)))

    def net_contributions(self, account_id: str, *, through: str | None = None) -> float:
        sql = """SELECT COALESCE(SUM(amount), 0) FROM cash_events
                 WHERE account_id = ? AND event_type IN ('initial_deposit', 'deposit', 'withdrawal')"""
        params: list[Any] = [account_id]
        if through:
            sql += " AND created_at <= ?"
            params.append(str(through))
        with self._connect() as connection:
            return float(connection.execute(sql, tuple(params)).fetchone()[0] or 0.0)

    def available_shares(self, account_id: str, symbol: str) -> float:
        with self._connect() as connection:
            position = connection.execute(
                "SELECT quantity FROM positions WHERE account_id = ? AND symbol = ?",
                (account_id, symbol),
            ).fetchone()
            held = float(position["quantity"] if position else 0.0)
            pending = float(
                connection.execute(
                    """SELECT COALESCE(SUM(quantity - filled_quantity), 0) FROM orders
                       WHERE account_id = ? AND symbol = ? AND side = 'sell' AND status = 'pending'""",
                    (account_id, symbol),
                ).fetchone()[0]
                or 0.0
            )
        return max(round(held - pending, 6), 0.0)

    def execute_order(
        self,
        order_id: str,
        quote: PaperQuote,
        *,
        fill_price: float,
        reference_price: float,
    ) -> dict[str, Any]:
        now = iso_utc()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            order_row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order_row is None:
                raise ValueError("Paper order was not found.")
            order = dict(order_row)
            if order["status"] != OrderStatus.PENDING:
                existing = connection.execute("SELECT * FROM fills WHERE order_id = ?", (order_id,)).fetchone()
                return dict(existing) if existing else {}
            quantity = float(order["quantity"])
            commission = float(order["commission_per_fill"])
            account_id = str(order["account_id"])
            symbol = str(order["symbol"])
            side = str(order["side"])
            position_row = connection.execute(
                "SELECT * FROM positions WHERE account_id = ? AND symbol = ?",
                (account_id, symbol),
            ).fetchone()
            old_quantity = float(position_row["quantity"] if position_row else 0.0)
            old_average = float(position_row["average_cost"] if position_row else 0.0)
            old_realized = float(position_row["realized_pnl"] if position_row else 0.0)
            cash = self.cash_balance(account_id, connection=connection)
            realized_delta = 0.0
            if side == "buy":
                total_cost = fill_price * quantity + commission
                if total_cost > cash + 1e-7:
                    self._transition_order(
                        connection,
                        order_id,
                        OrderStatus.REJECTED,
                        "rejected",
                        "Insufficient cash at execution price.",
                        now,
                        rejection_reason="Insufficient cash at execution price.",
                    )
                    return {}
                new_quantity = old_quantity + quantity
                new_average = (
                    (old_quantity * old_average + fill_price * quantity + commission) / new_quantity
                )
                cash_amount = -total_cost
            else:
                if quantity > old_quantity:
                    self._transition_order(
                        connection,
                        order_id,
                        OrderStatus.REJECTED,
                        "rejected",
                        "Insufficient shares at execution time.",
                        now,
                        rejection_reason="Insufficient shares at execution time.",
                    )
                    return {}
                new_quantity = old_quantity - quantity
                realized_delta = fill_price * quantity - commission - old_average * quantity
                new_quantity = 0.0 if abs(new_quantity) < 0.0000005 else round(new_quantity, 6)
                new_average = old_average if new_quantity > 0 else 0.0
                cash_amount = fill_price * quantity - commission
            fill_id = str(uuid.uuid4())
            fill_quote_timestamp = (
                quote.mark_timestamp
                if quote.market_state == "PRE" and quote.mark_session == "PRE"
                else quote.source_timestamp
            )
            fill_quote_source = (
                f"{quote.source} (pre-market bid/ask)"
                if quote.market_state == "PRE" and quote.mark_session == "PRE"
                else quote.source
            )
            connection.execute(
                """INSERT INTO fills
                   (id, order_id, account_id, symbol, side, quantity, quote_bid, quote_ask,
                    reference_price, fill_price, slippage_bps, commission, realized_pnl_delta,
                    quote_source, quote_timestamp, filled_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fill_id,
                    order_id,
                    account_id,
                    symbol,
                    side,
                    quantity,
                    quote.bid,
                    quote.ask,
                    reference_price,
                    fill_price,
                    order["slippage_bps"],
                    commission,
                    realized_delta,
                    fill_quote_source,
                    iso_utc(fill_quote_timestamp),
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO cash_events (id, account_id, fill_id, event_type, amount, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), account_id, fill_id, CashEventType.TRADE, cash_amount, now),
            )
            connection.execute(
                """INSERT INTO positions
                   (account_id, symbol, quantity, average_cost, realized_pnl, mark_price,
                    mark_source, mark_timestamp, mark_is_stale, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(account_id, symbol) DO UPDATE SET
                     quantity = excluded.quantity,
                     average_cost = excluded.average_cost,
                     realized_pnl = excluded.realized_pnl,
                     mark_price = excluded.mark_price,
                     mark_source = excluded.mark_source,
                     mark_timestamp = excluded.mark_timestamp,
                     mark_is_stale = 0,
                     updated_at = excluded.updated_at""",
                (
                    account_id,
                    symbol,
                    new_quantity,
                    new_average,
                    old_realized + realized_delta,
                    quote.bid,
                    quote.source,
                    iso_utc(quote.source_timestamp),
                    now,
                ),
            )
            connection.execute(
                """UPDATE orders
                   SET filled_quantity = quantity, status = 'filled', reserved_cash = 0,
                       last_evaluation = 'Filled',
                       triggered_at = CASE WHEN order_type = 'stop' THEN ? ELSE triggered_at END,
                       terminal_at = ?
                   WHERE id = ?""",
                (now, now, order_id),
            )
            connection.execute(
                """INSERT INTO order_events
                   (order_id, prior_status, new_status, event_type, message, created_at)
                   VALUES (?, 'pending', 'filled', 'filled', ?, ?)""",
                (order_id, f"Filled {quantity:.6f} {symbol} at ${fill_price:.4f}.", now),
            )
            fill = connection.execute("SELECT * FROM fills WHERE id = ?", (fill_id,)).fetchone()
        return dict(fill)

    def list_positions(self, account_id: str, *, include_closed: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM positions WHERE account_id = ?"
        if not include_closed:
            sql += " AND quantity > 0"
        sql += " ORDER BY symbol"
        with self._connect() as connection:
            return self._rows(connection.execute(sql, (account_id,)))

    def update_position_mark(self, account_id: str, quote: PaperQuote, *, stale: bool) -> None:
        mark = quote.mark_price if quote.mark_price and quote.mark_price > 0 else quote.bid if quote.bid and quote.bid > 0 else quote.last_price
        if mark is None:
            return
        source = f"{quote.source} (pre-market)" if quote.mark_session == "PRE" else quote.source
        with self._connect() as connection:
            connection.execute(
                """UPDATE positions SET mark_price = ?, mark_source = ?, mark_timestamp = ?,
                   mark_is_stale = ?, updated_at = ?
                   WHERE account_id = ? AND symbol = ? AND quantity > 0""",
                (
                    mark,
                    source,
                    iso_utc(quote.mark_timestamp or quote.source_timestamp or quote.fetched_at),
                    int(bool(stale or (quote.mark_session != "PRE" and not quote.bid))),
                    iso_utc(),
                    account_id,
                    quote.symbol,
                ),
            )

    def set_position_mark_stale(self, account_id: str, symbol: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE positions SET mark_is_stale = 1, updated_at = ?
                   WHERE account_id = ? AND symbol = ? AND quantity > 0""",
                (iso_utc(), account_id, str(symbol or "").upper().strip()),
            )

    def list_fills(self, account_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._rows(
                connection.execute(
                    "SELECT * FROM fills WHERE account_id = ? ORDER BY filled_at DESC LIMIT ?",
                    (account_id, max(1, int(limit))),
                )
            )

    def list_journal(self, account_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._rows(
                connection.execute(
                    "SELECT * FROM journal_entries WHERE account_id = ? ORDER BY updated_at DESC LIMIT ?",
                    (account_id, max(1, int(limit))),
                )
            )

    def save_journal_entry(
        self,
        account_id: str,
        note: str,
        tags: Iterable[str] = (),
        *,
        entry_id: str | None = None,
        order_id: str | None = None,
        fill_id: str | None = None,
    ) -> dict[str, Any]:
        clean_note = str(note or "").strip()[:4000]
        clean_tags = list(dict.fromkeys(str(tag).strip()[:40] for tag in tags if str(tag).strip()))[:12]
        now = iso_utc()
        journal_id = str(entry_id or uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO journal_entries
                   (id, account_id, order_id, fill_id, note, tags_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     note = excluded.note, tags_json = excluded.tags_json, updated_at = excluded.updated_at""",
                (journal_id, account_id, order_id, fill_id, clean_note, json.dumps(clean_tags), now, now),
            )
            row = connection.execute("SELECT * FROM journal_entries WHERE id = ?", (journal_id,)).fetchone()
        return dict(row)

    def account_summary(self, account_id: str) -> dict[str, Any]:
        positions = self.list_positions(account_id)
        cash = self.cash_balance(account_id)
        reserved = self.reserved_cash(account_id)
        market_value = 0.0
        unrealized = 0.0
        stale_count = 0
        for position in positions:
            quantity = float(position["quantity"])
            mark = float(position["mark_price"] or position["average_cost"] or 0.0)
            market_value += quantity * mark
            unrealized += quantity * (mark - float(position["average_cost"] or 0.0))
            stale_count += int(bool(position["mark_is_stale"]))
        with self._connect() as connection:
            realized = float(
                connection.execute(
                    "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE account_id = ?",
                    (account_id,),
                ).fetchone()[0]
                or 0.0
            )
        return {
            "cash": cash,
            "reserved_cash": reserved,
            "buying_power": max(cash - reserved, 0.0),
            "market_value": market_value,
            "equity": cash + market_value,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "stale_mark_count": stale_count,
        }

    def record_equity_snapshot(self, account_id: str, *, force: bool = False) -> bool:
        now = dt.datetime.now(dt.timezone.utc)
        with self._connect() as connection:
            latest = connection.execute(
                "SELECT created_at FROM equity_snapshots WHERE account_id = ? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            if not force and latest:
                try:
                    last_time = dt.datetime.fromisoformat(str(latest["created_at"]).replace("Z", "+00:00"))
                    if (now - last_time.astimezone(dt.timezone.utc)).total_seconds() < 300:
                        return False
                except ValueError:
                    pass
            summary = self.account_summary(account_id)
            connection.execute(
                """INSERT INTO equity_snapshots
                   (account_id, cash, market_value, equity, realized_pnl, unrealized_pnl,
                    stale_mark_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    account_id,
                    summary["cash"],
                    summary["market_value"],
                    summary["equity"],
                    summary["realized_pnl"],
                    summary["unrealized_pnl"],
                    summary["stale_mark_count"],
                    iso_utc(now),
                ),
            )
        return True

    def list_equity_snapshots(self, account_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = self._rows(
                connection.execute(
                    """SELECT * FROM equity_snapshots WHERE account_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (account_id, max(1, int(limit))),
                )
            )
        rows.reverse()
        return rows

    def build_backup(self) -> dict[str, Any]:
        with self._maintenance_lock, self._connect() as connection:
            tables = {
                table: self._rows(connection.execute(f'SELECT * FROM "{table}"'))
                for table in _TABLES
            }
        return {
            "backup_type": "budget_terminal_paper_trading",
            "version": PAPER_BACKUP_VERSION,
            "database_version": PAPER_DATABASE_VERSION,
            "exported_at": iso_utc(),
            "tables": tables,
        }

    def export_backup(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.build_backup(), indent=2), encoding="utf-8")

    @staticmethod
    def load_backup(path: str | Path) -> dict[str, Any]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Unable to read the paper-trading backup.") from exc
        if not isinstance(payload, dict) or payload.get("backup_type") != "budget_terminal_paper_trading":
            raise ValueError("The selected file is not a Budget Terminal paper-trading backup.")
        version = int(payload.get("version", 0) or 0)
        if version not in SUPPORTED_PAPER_BACKUP_VERSIONS:
            raise ValueError("The paper-trading backup version is not supported.")
        tables = payload.get("tables")
        if not isinstance(tables, dict):
            raise ValueError("The paper-trading backup is incomplete.")
        if version < 4:
            payload = dict(payload)
            tables = dict(tables)
            tables.setdefault("recurring_schedules", [])
            tables.setdefault("recurring_runs", [])
            payload["tables"] = tables
        if any(not isinstance(tables.get(table), list) for table in _TABLES):
            raise ValueError("The paper-trading backup is incomplete.")
        return payload

    def _rollback_path(self, reason: str) -> Path:
        PAPER_ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_reason = "".join(char if char.isalnum() else "_" for char in reason).strip("_") or "backup"
        path = PAPER_ROLLBACK_DIR / f"paper_{safe_reason}_{timestamp}.db"
        suffix = 1
        while path.exists():
            path = PAPER_ROLLBACK_DIR / f"paper_{safe_reason}_{timestamp}_{suffix}.db"
            suffix += 1
        return path

    def create_rollback_backup(self, *, reason: str) -> str:
        target = self._rollback_path(reason)
        with self._maintenance_lock, self._connect() as source, sqlite3.connect(
            target,
            factory=_ClosingConnection,
        ) as destination:
            source.backup(destination)
        return str(target)

    def import_backup(self, payload: dict[str, Any]) -> str:
        tables = payload.get("tables") if isinstance(payload, dict) else None
        if not isinstance(tables, dict):
            raise ValueError("The paper-trading backup is incomplete.")
        self._validate_backup_tables(tables)
        rollback = self.create_rollback_backup(reason="before_import")
        try:
            with self._maintenance_lock, self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for table in reversed(_TABLES):
                    connection.execute(f'DELETE FROM "{table}"')
                for table in _TABLES:
                    rows = tables.get(table, [])
                    if not isinstance(rows, list):
                        raise ValueError(f"Backup table {table!r} is invalid.")
                    for row in rows:
                        if not isinstance(row, dict) or not row:
                            raise ValueError(f"Backup table {table!r} contains an invalid row.")
                        columns = list(row)
                        placeholders = ", ".join("?" for _ in columns)
                        column_sql = ", ".join(f'"{column}"' for column in columns)
                        connection.execute(
                            f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                            tuple(row[column] for column in columns),
                        )
                problems = connection.execute("PRAGMA foreign_key_check").fetchall()
                if problems:
                    raise ValueError("Backup relationships failed validation.")
        except Exception:
            raise
        return rollback

    @staticmethod
    def _validate_backup_tables(tables: dict[str, Any]) -> None:
        accounts = tables.get("accounts", [])
        if len(accounts) > 5:
            raise ValueError("A paper backup cannot contain more than five accounts.")
        for account in accounts:
            if not isinstance(account, dict):
                raise ValueError("The accounts table contains an invalid row.")
            if account.get("currency") != "USD" or account.get("status") not in {"active", "archived"}:
                raise ValueError("A paper account has an unsupported currency or status.")
            if float(account.get("initial_cash") or 0.0) <= 0:
                raise ValueError("A paper account has invalid starting cash.")
        valid_cash_types = {"initial_deposit", "deposit", "withdrawal", "trade"}
        for event in tables.get("cash_events", []):
            if not isinstance(event, dict) or event.get("event_type") not in valid_cash_types:
                raise ValueError("A paper cash event has an unsupported type.")
            amount = float(event.get("amount") or 0.0)
            event_type = str(event.get("event_type") or "")
            if event_type in {"initial_deposit", "deposit"} and amount <= 0:
                raise ValueError("A paper deposit must be greater than zero.")
            if event_type == "withdrawal" and amount >= 0:
                raise ValueError("A paper withdrawal must be less than zero.")
        schedule_ids = set()
        for schedule in tables.get("recurring_schedules", []):
            if not isinstance(schedule, dict):
                raise ValueError("A recurring schedule contains an invalid row.")
            schedule_ids.add(str(schedule.get("id") or ""))
            try:
                RecurringScheduleSpec(
                    account_id=str(schedule.get("account_id") or ""),
                    kind=str(schedule.get("kind") or ""),
                    cadence=str(schedule.get("cadence") or ""),
                    amount=float(schedule.get("amount") or 0.0),
                    symbol=str(schedule.get("symbol") or ""),
                    timezone=str(schedule.get("timezone") or "LOCAL"),
                    local_time=str(schedule.get("local_time") or ""),
                    weekday=schedule.get("weekday"),
                    month_day=schedule.get("month_day"),
                ).normalized()
                RecurringStatus(str(schedule.get("status") or ""))
            except (TypeError, ValueError) as exc:
                raise ValueError("A recurring schedule is invalid.") from exc
        for run in tables.get("recurring_runs", []):
            if not isinstance(run, dict) or str(run.get("schedule_id") or "") not in schedule_ids:
                raise ValueError("A recurring run contains an invalid schedule reference.")
            try:
                RecurringRunStatus(str(run.get("status") or ""))
            except ValueError as exc:
                raise ValueError("A recurring run has an unsupported status.") from exc
        for order in tables.get("orders", []):
            if not isinstance(order, dict):
                raise ValueError("The orders table contains an invalid row.")
            quantity = float(order.get("quantity") or 0.0)
            filled = float(order.get("filled_quantity") or 0.0)
            if quantity <= 0 or not (abs(filled) < 1e-7 or abs(filled - quantity) < 1e-7):
                raise ValueError("A paper order violates the full-fill quantity contract.")
            if order.get("order_type") == "market" and order.get("tif") != "day":
                raise ValueError("A market order in the backup does not use DAY time-in-force.")
            execution_session = str(order.get("execution_session") or "regular")
            if execution_session not in {"regular", "extended"}:
                raise ValueError("A paper order has an unsupported trading-hours session.")
            if execution_session == "extended" and (
                order.get("order_type") != "limit" or order.get("tif") != "day"
            ):
                raise ValueError("A pre-market eligible order must be a DAY limit order.")
            if order.get("status") == "filled" and abs(filled - quantity) >= 1e-7:
                raise ValueError("A filled paper order has an invalid filled quantity.")
            if order.get("status") != "filled" and abs(filled) >= 1e-7:
                raise ValueError("A non-filled paper order cannot contain a fill quantity.")
        for position in tables.get("positions", []):
            if not isinstance(position, dict) or float(position.get("quantity") or 0.0) < 0:
                raise ValueError("A paper position contains an invalid quantity.")

    def reset(self) -> str:
        rollback = self.create_rollback_backup(reason="before_reset")
        with self._maintenance_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM accounts")
            connection.execute("DELETE FROM sqlite_sequence WHERE name IN ('order_events', 'equity_snapshots')")
        return rollback


def _positive_finite(value: Any, label: str) -> float:
    number = _nonnegative_finite(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be greater than $0.")
    return number


def _nonnegative_finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be zero or greater.")
    return round(number, 6)
