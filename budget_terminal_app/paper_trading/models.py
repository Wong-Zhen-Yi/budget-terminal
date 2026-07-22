from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo


class AccountStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"


class OrderSession(StrEnum):
    REGULAR = "regular"
    EXTENDED = "extended"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class CashEventType(StrEnum):
    INITIAL_DEPOSIT = "initial_deposit"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRADE = "trade"


class RecurringKind(StrEnum):
    FUNDING = "funding"
    BUY = "buy"


class RecurringCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class RecurringStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class RecurringRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class RecurringScheduleSpec:
    account_id: str
    kind: RecurringKind | str
    cadence: RecurringCadence | str
    amount: float
    local_time: str
    timezone: str = "LOCAL"
    symbol: str = ""
    weekday: int | None = None
    month_day: int | None = None

    def normalized(self) -> "RecurringScheduleSpec":
        account_id = str(self.account_id or "").strip()
        if not account_id:
            raise ValueError("An account is required for the recurring schedule.")
        kind = RecurringKind(str(self.kind).lower())
        cadence = RecurringCadence(str(self.cadence).lower())
        amount = _positive_optional(self.amount, "Recurring amount")
        if amount is None or amount < 0.01 or amount > 1_000_000_000:
            raise ValueError("Recurring amount must be between $0.01 and $1,000,000,000.00.")
        try:
            parsed_time = dt.time.fromisoformat(str(self.local_time or ""))
        except ValueError as exc:
            raise ValueError("Choose a valid recurring time.") from exc
        local_time = parsed_time.replace(second=0, microsecond=0).isoformat(timespec="minutes")
        timezone = str(self.timezone or "LOCAL").strip() or "LOCAL"
        if timezone != "LOCAL":
            try:
                ZoneInfo(timezone)
            except Exception as exc:
                raise ValueError("Choose a valid schedule timezone.") from exc
        symbol = str(self.symbol or "").upper().strip()
        if kind is RecurringKind.BUY:
            if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
                raise ValueError("Enter a valid US stock or ETF symbol.")
        else:
            symbol = ""
        weekday = int(self.weekday) if self.weekday is not None else None
        month_day = int(self.month_day) if self.month_day is not None else None
        if cadence is RecurringCadence.WEEKLY and (weekday is None or weekday not in range(7)):
            raise ValueError("Choose a weekday for the weekly schedule.")
        if cadence is RecurringCadence.MONTHLY and (month_day is None or not 1 <= month_day <= 31):
            raise ValueError("Choose a day from 1 through 31 for the monthly schedule.")
        return RecurringScheduleSpec(
            account_id=account_id,
            kind=kind,
            cadence=cadence,
            amount=amount,
            local_time=local_time,
            timezone=timezone,
            symbol=symbol,
            weekday=weekday if cadence is RecurringCadence.WEEKLY else None,
            month_day=month_day if cadence is RecurringCadence.MONTHLY else None,
        )


@dataclass(frozen=True)
class PaperOrderRequest:
    account_id: str
    symbol: str
    side: OrderSide | str
    quantity: float
    order_type: OrderType | str
    tif: TimeInForce | str
    limit_price: float | None = None
    stop_price: float | None = None
    reasoning: str = ""
    tags: tuple[str, ...] = ()
    execution_session: OrderSession | str = OrderSession.REGULAR

    def normalized(self) -> "PaperOrderRequest":
        symbol = str(self.symbol or "").upper().strip()
        side = OrderSide(str(self.side).lower())
        order_type = OrderType(str(self.order_type).lower())
        tif = TimeInForce(str(self.tif).lower())
        execution_session = OrderSession(str(self.execution_session).lower())
        quantity = normalize_share_quantity(self.quantity)
        if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
            raise ValueError("Enter a valid US stock or ETF symbol.")
        if order_type is OrderType.MARKET and tif is not TimeInForce.DAY:
            raise ValueError("Market orders support DAY time-in-force only.")
        if execution_session is OrderSession.EXTENDED:
            if order_type is not OrderType.LIMIT:
                raise ValueError("Pre-market eligibility supports limit orders only.")
            if tif is not TimeInForce.DAY:
                raise ValueError("Pre-market eligible orders support DAY time-in-force only.")
        limit_price = _positive_optional(self.limit_price, "Limit price")
        stop_price = _positive_optional(self.stop_price, "Stop price")
        if order_type is OrderType.LIMIT and limit_price is None:
            raise ValueError("A limit price is required for limit orders.")
        if order_type is OrderType.STOP and stop_price is None:
            raise ValueError("A stop price is required for stop orders.")
        tags = tuple(dict.fromkeys(str(tag).strip()[:40] for tag in self.tags if str(tag).strip()))[:12]
        return PaperOrderRequest(
            account_id=str(self.account_id or "").strip(),
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            tif=tif,
            limit_price=limit_price if order_type is OrderType.LIMIT else None,
            stop_price=stop_price if order_type is OrderType.STOP else None,
            reasoning=str(self.reasoning or "").strip()[:4000],
            tags=tags,
            execution_session=execution_session,
        )


@dataclass(frozen=True)
class PaperQuote:
    symbol: str
    bid: float | None
    ask: float | None
    bid_size: int | None
    ask_size: int | None
    last_price: float | None
    exchange: str
    currency: str
    quote_type: str
    market_state: str
    source_timestamp: dt.datetime | None
    fetched_at: dt.datetime
    source: str = "Yahoo Finance"
    mark_price: float | None = None
    mark_timestamp: dt.datetime | None = None
    mark_session: str = ""

    @property
    def has_executable_spread(self) -> bool:
        return bool(
            self.bid is not None
            and self.ask is not None
            and self.bid > 0
            and self.ask > 0
            and self.ask >= self.bid
        )

    def age_seconds(self, now: dt.datetime | None = None) -> float | None:
        if self.source_timestamp is None:
            return None
        current = ensure_utc(now or dt.datetime.now(dt.timezone.utc))
        return max((current - ensure_utc(self.source_timestamp)).total_seconds(), 0.0)

    def mark_age_seconds(self, now: dt.datetime | None = None) -> float | None:
        timestamp = self.mark_timestamp or self.source_timestamp
        if timestamp is None:
            return None
        current = ensure_utc(now or dt.datetime.now(dt.timezone.utc))
        return max((current - ensure_utc(timestamp)).total_seconds(), 0.0)


def ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def iso_utc(value: dt.datetime | None = None) -> str:
    return ensure_utc(value or dt.datetime.now(dt.timezone.utc)).isoformat()


def parse_timestamp(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return ensure_utc(value)
    try:
        if isinstance(value, (int, float)):
            return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
        return ensure_utc(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError, OSError):
        return None


def _positive_optional(value: Any, label: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be greater than $0.")
    return round(number, 6)


def normalize_share_quantity(value: Any) -> float:
    try:
        quantity = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantity must be a number.") from exc
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    rounded = round(quantity, 6)
    if rounded < 0.000001:
        raise ValueError("Quantity must be at least 0.000001 share.")
    return rounded


def format_share_quantity(value: Any) -> str:
    quantity = round(float(value or 0.0), 6)
    return f"{quantity:,.6f}".rstrip("0").rstrip(".")
