from __future__ import annotations

import calendar
import datetime as dt
import math
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .engine import PaperTradingEngine
from .models import (
    PaperOrderRequest,
    RecurringCadence,
    RecurringKind,
    RecurringRunStatus,
    RecurringScheduleSpec,
    ensure_utc,
    format_share_quantity,
    iso_utc,
    parse_timestamp,
)
from .quotes import YahooPaperQuoteService
from .store import PaperTradingStore


def recurring_timezone(name: str) -> dt.tzinfo:
    if str(name or "LOCAL").upper() == "LOCAL":
        return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc
    return ZoneInfo(str(name))


def _schedule_value(schedule: RecurringScheduleSpec | dict[str, Any], key: str) -> Any:
    if isinstance(schedule, RecurringScheduleSpec):
        return getattr(schedule, key)
    return schedule.get(key)


def next_recurring_run(
    schedule: RecurringScheduleSpec | dict[str, Any],
    after: dt.datetime,
) -> dt.datetime:
    timezone = recurring_timezone(str(_schedule_value(schedule, "timezone") or "LOCAL"))
    current = ensure_utc(after).astimezone(timezone)
    local_time = dt.time.fromisoformat(str(_schedule_value(schedule, "local_time")))
    cadence = RecurringCadence(str(_schedule_value(schedule, "cadence")))

    def at_local(date_value: dt.date) -> dt.datetime:
        return dt.datetime.combine(date_value, local_time, tzinfo=timezone)

    if cadence is RecurringCadence.DAILY:
        candidate = at_local(current.date())
        if candidate <= current:
            candidate = at_local(current.date() + dt.timedelta(days=1))
    elif cadence is RecurringCadence.WEEKLY:
        weekday = int(_schedule_value(schedule, "weekday"))
        days_ahead = (weekday - current.weekday()) % 7
        candidate = at_local(current.date() + dt.timedelta(days=days_ahead))
        if candidate <= current:
            candidate = at_local(candidate.date() + dt.timedelta(days=7))
    else:
        month_day = int(_schedule_value(schedule, "month_day"))

        def monthly_candidate(year: int, month: int) -> dt.datetime:
            day = min(month_day, calendar.monthrange(year, month)[1])
            return at_local(dt.date(year, month, day))

        candidate = monthly_candidate(current.year, current.month)
        if candidate <= current:
            year = current.year + (1 if current.month == 12 else 0)
            month = 1 if current.month == 12 else current.month + 1
            candidate = monthly_candidate(year, month)
    return candidate.astimezone(dt.timezone.utc)


def recurring_due_window(schedule: dict[str, Any], now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    current = ensure_utc(now)
    due = parse_timestamp(schedule.get("next_run_at"))
    if due is None or due > current:
        raise ValueError("Recurring schedule is not currently due.")
    future = next_recurring_run(schedule, due)
    iterations = 0
    while future <= current:
        due = future
        future = next_recurring_run(schedule, due)
        iterations += 1
        if iterations > 100_000:
            raise RuntimeError("Recurring schedule could not advance to a future occurrence.")
    return due, future


class RecurringTradingService:
    """Execute due local recurring funding and Virtual buy schedules."""

    def __init__(
        self,
        store: PaperTradingStore | None = None,
        quote_service: YahooPaperQuoteService | None = None,
        *,
        now: Callable[[], dt.datetime] | None = None,
        trading_day_resolver: Callable[[dt.date], bool] | None = None,
    ) -> None:
        self.store = store or PaperTradingStore()
        self.quote_service = quote_service or YahooPaperQuoteService()
        self._now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self._trading_day_resolver = trading_day_resolver or self._is_nyse_trading_day
        self.engine = PaperTradingEngine(
            self.store,
            self.quote_service,
            now=self._now,
            allow_premarket_marks=True,
            instant_fill=True,
        )

    @staticmethod
    def _is_nyse_trading_day(date_value: dt.date) -> bool:
        import pandas_market_calendars as market_calendars

        schedule = market_calendars.get_calendar("NYSE").schedule(
            start_date=date_value,
            end_date=date_value,
        )
        return not schedule.empty

    @staticmethod
    def schedule_local_date(schedule: dict[str, Any], scheduled_for: dt.datetime) -> dt.date:
        timezone = recurring_timezone(str(schedule.get("timezone") or "LOCAL"))
        return ensure_utc(scheduled_for).astimezone(timezone).date()

    def run_due(self, now: dt.datetime | None = None) -> dict[str, Any]:
        current = ensure_utc(now or self._now())
        current_iso = iso_utc(current)
        result: dict[str, Any] = {"claimed": 0, "success": 0, "skipped": 0, "failed": 0, "runs": []}
        for schedule in self.store.due_recurring_schedules(current_iso):
            run = None
            try:
                scheduled_for, next_run = recurring_due_window(schedule, current)
                run = self.store.claim_recurring_run(
                    schedule["id"],
                    scheduled_for=iso_utc(scheduled_for),
                    next_run_at=iso_utc(next_run),
                    started_at=current_iso,
                )
                if run is None:
                    continue
                result["claimed"] += 1
                if schedule["kind"] == RecurringKind.FUNDING:
                    self.store.apply_scheduled_funding(run["id"], completed_at=current_iso)
                    self.store.record_equity_snapshot(schedule["account_id"], force=True)
                    terminal = self.store.list_recurring_runs(schedule["id"], limit=1)[0]
                else:
                    terminal = self._run_buy(schedule, run, scheduled_for, current_iso)
            except Exception as exc:
                if run is not None and run.get("status") == RecurringRunStatus.RUNNING:
                    try:
                        terminal = self.store.complete_recurring_run(
                            run["id"],
                            RecurringRunStatus.FAILED,
                            message=str(exc),
                            completed_at=current_iso,
                        )
                    except Exception:
                        terminal = {"status": RecurringRunStatus.FAILED, "message": str(exc)}
                else:
                    terminal = {"status": RecurringRunStatus.FAILED, "message": str(exc)}
            status = str(terminal.get("status") or RecurringRunStatus.FAILED)
            result[status] = int(result.get(status, 0)) + 1
            result["runs"].append(terminal)
        return result

    def _run_buy(
        self,
        schedule: dict[str, Any],
        run: dict[str, Any],
        scheduled_for: dt.datetime,
        completed_at: str,
    ) -> dict[str, Any]:
        scheduled_date = self.schedule_local_date(schedule, scheduled_for)
        if not self._trading_day_resolver(scheduled_date):
            return self.store.complete_recurring_run(
                run["id"],
                RecurringRunStatus.SKIPPED,
                message=f"Skipped because {scheduled_date.isoformat()} is not an NYSE trading day.",
                completed_at=completed_at,
            )
        amount = float(schedule["amount"])
        summary = self.store.account_summary(schedule["account_id"])
        if float(summary["buying_power"]) + 1e-7 < amount:
            return self.store.complete_recurring_run(
                run["id"],
                RecurringRunStatus.SKIPPED,
                message=f"Skipped: ${amount:,.2f} scheduled, ${float(summary['buying_power']):,.2f} available.",
                completed_at=completed_at,
            )
        account = self.store.get_account(schedule["account_id"])
        commission = float(account.get("commission_per_fill") or 0.0)
        investable = amount - commission
        if investable <= 0:
            return self.store.complete_recurring_run(
                run["id"],
                RecurringRunStatus.SKIPPED,
                message="Skipped because commission consumes the recurring buy amount.",
                completed_at=completed_at,
            )
        try:
            quote = self.quote_service.fetch(str(schedule["symbol"]))
            self.engine._validate_security(quote)
            reference = (
                float(quote.mark_price)
                if quote.market_state == "PRE" and quote.mark_price and quote.mark_price > 0
                else float(quote.last_price or 0.0)
            )
            if reference <= 0:
                raise ValueError("Yahoo did not return a usable Virtual price.")
            slippage = float(account.get("slippage_bps") or 0.0) / 10_000.0
            fill_price = round(reference * (1.0 + slippage), 6)
            quantity = math.floor((investable / fill_price) * 1_000_000) / 1_000_000
            if quantity < 0.000001:
                raise ValueError("The recurring amount buys less than 0.000001 share.")
            request = PaperOrderRequest(
                account_id=schedule["account_id"],
                symbol=schedule["symbol"],
                side="buy",
                quantity=quantity,
                order_type="market",
                tif="day",
                execution_session="regular",
            )
            order, fill = self.engine.submit_instant_order(
                request,
                quote=quote,
                recurring_run_id=run["id"],
            )
        except Exception as exc:
            return self.store.complete_recurring_run(
                run["id"],
                RecurringRunStatus.SKIPPED,
                message=f"Skipped: {exc}",
                completed_at=completed_at,
            )
        return self.store.complete_recurring_run(
            run["id"],
            RecurringRunStatus.SUCCESS,
            message=(
                f"Bought {format_share_quantity(quantity)} {schedule['symbol']} for "
                f"${float(fill['fill_price']) * quantity + float(fill['commission']):,.2f}."
            ),
            quantity=quantity,
            reference_price=float(fill["fill_price"]),
            completed_at=completed_at,
        )
