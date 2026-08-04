from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from .models import (
    OrderSide,
    OrderSession,
    OrderStatus,
    OrderType,
    PaperOrderRequest,
    PaperQuote,
    TimeInForce,
    ensure_utc,
    format_share_quantity,
    parse_timestamp,
)
from .quotes import YahooPaperQuoteService
from .store import PaperTradingStore


@dataclass(frozen=True)
class MarketSession:
    is_open: bool
    current_close: dt.datetime | None
    next_close: dt.datetime | None
    is_premarket: bool = False


class PaperTradingEngine:
    """Validate and execute deterministic long-only stock and ETF cash-account orders."""

    MAJOR_US_EXCHANGES = {"NYQ", "NMS", "NGM", "NCM", "ASE", "NYSE", "NASDAQ"}
    MAJOR_US_ETF_EXCHANGES = MAJOR_US_EXCHANGES | {"PCX", "ARCX", "BTS", "BATS"}
    SUPPORTED_QUOTE_TYPES = {"EQUITY", "ETF"}
    MAX_QUOTE_AGE_SECONDS = 20 * 60

    def __init__(
        self,
        store: PaperTradingStore,
        quote_service: YahooPaperQuoteService | None = None,
        *,
        now: Callable[[], dt.datetime] | None = None,
        session_resolver: Callable[[dt.datetime], MarketSession] | None = None,
        allow_premarket_marks: bool = False,
        instant_fill: bool = False,
    ) -> None:
        self.store = store
        self.quote_service = quote_service or YahooPaperQuoteService()
        self._now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self._session_resolver = session_resolver or self._resolve_us_session
        self.allow_premarket_marks = bool(allow_premarket_marks)
        self.instant_fill = bool(instant_fill)

    def session(self, now: dt.datetime | None = None) -> MarketSession:
        return self._session_resolver(ensure_utc(now or self._now()))

    @staticmethod
    def _resolve_us_session(now: dt.datetime) -> MarketSession:
        import pandas_market_calendars as market_calendars

        current = ensure_utc(now)
        eastern_date = current.astimezone(ZoneInfo("America/New_York")).date()
        calendar = market_calendars.get_calendar("NYSE")
        schedule = calendar.schedule(
            start_date=eastern_date - dt.timedelta(days=2),
            end_date=eastern_date + dt.timedelta(days=10),
        )
        current_close: dt.datetime | None = None
        next_close: dt.datetime | None = None
        is_open = False
        is_premarket = False
        for _, row in schedule.iterrows():
            market_open = ensure_utc(row["market_open"].to_pydatetime())
            market_close = ensure_utc(row["market_close"].to_pydatetime())
            if market_open.astimezone(ZoneInfo("America/New_York")).date() == eastern_date:
                premarket_open = market_open - dt.timedelta(hours=5, minutes=30)
                is_premarket = premarket_open <= current < market_open
            if market_open <= current < market_close:
                is_open = True
                current_close = market_close
                next_close = market_close
                break
            if current < market_close and next_close is None:
                next_close = market_close
        return MarketSession(
            is_open=is_open,
            current_close=current_close,
            next_close=next_close,
            is_premarket=is_premarket,
        )

    def submit_order(
        self,
        request: PaperOrderRequest,
        *,
        quote: PaperQuote | None = None,
    ) -> dict[str, Any]:
        normalized = request.normalized()
        account = self.store.get_account(normalized.account_id)
        resolved_quote = quote or self.quote_service.fetch(normalized.symbol)
        self._validate_security(resolved_quote)
        reserved_cash = self.reservation_required(normalized, account, resolved_quote)
        if normalized.side is OrderSide.BUY:
            buying_power = self.store.cash_balance(normalized.account_id) - self.store.reserved_cash(
                normalized.account_id
            )
            if reserved_cash > buying_power + 1e-7:
                raise ValueError("Insufficient buying power after open-order reservations.")
        else:
            available = self.store.available_shares(normalized.account_id, normalized.symbol)
            if normalized.quantity > available:
                raise ValueError(f"Only {format_share_quantity(available)} unreserved share(s) are available to sell.")
        expires_at = None
        if normalized.tif is TimeInForce.DAY:
            session = self.session()
            expires_at = session.current_close if session.is_open else session.next_close
            if expires_at is None:
                raise RuntimeError("Unable to resolve the next US market session.")
        return self.store.create_order(
            normalized,
            expires_at=expires_at,
            reserved_cash=reserved_cash,
        )

    def submit_instant_order(
        self,
        request: PaperOrderRequest,
        *,
        quote: PaperQuote,
        recurring_run_id: str | None = None,
        executed_at: dt.datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Create and fill exactly one Virtual order without evaluating unrelated pending orders."""
        if not self.instant_fill:
            raise RuntimeError("Targeted instant execution is available to Virtual orders only.")
        normalized = request.normalized()
        account = self.store.get_account(normalized.account_id)
        self._validate_security(quote)
        if normalized.side is OrderSide.SELL:
            available = self.store.available_shares(normalized.account_id, normalized.symbol)
            if normalized.quantity > available + 1e-7:
                raise ValueError(
                    f"Only {format_share_quantity(available)} unreserved share(s) are available to sell."
                )
        provisional = {
            "side": normalized.side,
            "order_type": normalized.order_type,
            "limit_price": normalized.limit_price,
            "stop_price": normalized.stop_price,
            "slippage_bps": account["slippage_bps"],
        }
        execution = self._instant_execution_price(provisional, quote)
        if execution is None:
            raise ValueError("A usable Virtual execution price was not available.")
        fill_price, reference_price, execution_quote = execution
        commission = float(account.get("commission_per_fill") or 0.0)
        reserved_cash = 0.0
        if normalized.side is OrderSide.BUY:
            reserved_cash = round(fill_price * normalized.quantity + commission, 6)
            buying_power = self.store.cash_balance(normalized.account_id) - self.store.reserved_cash(
                normalized.account_id
            )
            if reserved_cash > buying_power + 1e-7:
                raise ValueError("Insufficient buying power for the targeted Virtual order.")
        order = self.store.create_order(
            normalized,
            expires_at=None,
            reserved_cash=reserved_cash,
            recurring_run_id=recurring_run_id,
            submitted_at=executed_at,
        )
        fill = self.store.execute_order(
            order["id"],
            execution_quote,
            fill_price=fill_price,
            reference_price=reference_price,
            executed_at=executed_at,
        )
        if not fill:
            raise ValueError("The targeted Virtual order was not filled.")
        self.store.record_equity_snapshot(normalized.account_id, force=True)
        return self.store.get_order(order["id"]), fill

    @staticmethod
    def _reservation(
        request: PaperOrderRequest,
        account: dict[str, Any],
        quote: PaperQuote,
    ) -> float:
        if request.side is OrderSide.SELL:
            return 0.0
        commission = float(account.get("commission_per_fill") or 0.0)
        slippage = float(account.get("slippage_bps") or 0.0) / 10000.0
        if request.order_type is OrderType.LIMIT:
            reference = float(request.limit_price or 0.0)
            if reference <= 0:
                raise ValueError("A valid limit price is required to reserve buying power.")
            return round(request.quantity * reference + commission, 6)
        else:
            reference = float(quote.ask or quote.last_price or 0.0)
            if request.order_type is OrderType.STOP:
                reference = max(reference, float(request.stop_price or 0.0))
        if reference <= 0:
            raise ValueError("A current quote is required to reserve buying power.")
        return round(request.quantity * reference * (1.0 + slippage) * 1.02 + commission, 6)

    def reservation_required(
        self,
        request: PaperOrderRequest,
        account: dict[str, Any],
        quote: PaperQuote,
    ) -> float:
        reservation_quote = quote
        if self.instant_fill:
            reference = (
                float(quote.mark_price)
                if quote.market_state == "PRE" and quote.mark_price and quote.mark_price > 0
                else float(quote.last_price or 0.0)
            )
            reservation_quote = replace(
                quote,
                bid=reference or None,
                ask=reference or None,
                last_price=reference or None,
            )
        return self._reservation(request, account, reservation_quote)

    def process_pending_orders(
        self,
        *,
        quotes: dict[str, PaperQuote] | None = None,
        fetch_missing: bool = True,
    ) -> dict[str, Any]:
        now = ensure_utc(self._now())
        session = self.session(now)
        pending = self.store.pending_orders()
        result = {"evaluated": 0, "filled": 0, "expired": 0, "rejected": 0, "errors": []}
        quote_cache = dict(quotes or {})
        for order in pending:
            expires_at = parse_timestamp(order.get("expires_at"))
            if not self.instant_fill and expires_at is not None and now >= expires_at:
                self.store.expire_order(order["id"], message="DAY order expired at the regular-session close.")
                result["expired"] += 1
                continue
            execution_session = OrderSession(str(order.get("execution_session") or OrderSession.REGULAR))
            premarket_eligible = bool(
                session.is_premarket and execution_session is OrderSession.EXTENDED
            )
            if not self.instant_fill and not session.is_open and not premarket_eligible:
                waiting = (
                    "Waiting for the next US pre-market session."
                    if execution_session is OrderSession.EXTENDED
                    else "Waiting for the regular US market session."
                )
                self.store.update_order_evaluation(order["id"], waiting)
                continue
            symbol = str(order["symbol"])
            try:
                quote = quote_cache.get(symbol)
                if quote is None:
                    if not fetch_missing:
                        self.store.update_order_evaluation(order["id"], "Yahoo quote was unavailable this cycle.")
                        continue
                    quote = self.quote_service.fetch(symbol)
                    quote_cache[symbol] = quote
                market_phase = "premarket" if premarket_eligible else "regular"
                order_type = OrderType(str(order["order_type"]))
                reason = (
                    ""
                    if self.instant_fill and order_type in {OrderType.LIMIT, OrderType.STOP}
                    else self.quote_execution_block(quote, now=now, market_phase=market_phase)
                )
                if reason:
                    self.store.update_order_evaluation(order["id"], reason)
                    continue
                result["evaluated"] += 1
                execution_quote = quote
                if self.instant_fill:
                    instant_execution = self._instant_execution_price(order, quote)
                    if instant_execution is None:
                        execution = None
                    else:
                        fill_price, reference_price, execution_quote = instant_execution
                        execution = (fill_price, reference_price)
                else:
                    execution = self._execution_price(order, quote)
                if execution is None:
                    self.store.update_order_evaluation(order["id"], self._waiting_message(order, quote))
                    continue
                fill_price, reference_price = execution
                fill = self.store.execute_order(
                    order["id"],
                    execution_quote,
                    fill_price=fill_price,
                    reference_price=reference_price,
                )
                refreshed = self.store.get_order(order["id"])
                if fill:
                    result["filled"] += 1
                    self.store.record_equity_snapshot(order["account_id"], force=True)
                elif refreshed["status"] == OrderStatus.REJECTED:
                    result["rejected"] += 1
            except Exception as exc:
                message = f"Quote evaluation failed: {exc}"
                self.store.update_order_evaluation(order["id"], message)
                result["errors"].append({"order_id": order["id"], "symbol": symbol, "reason": str(exc)})
        return result

    def mark_accounts(
        self,
        account_ids: Iterable[str] | None = None,
        *,
        quotes: dict[str, PaperQuote] | None = None,
        fetch_missing: bool = True,
        required_mark_session: str = "",
    ) -> dict[str, Any]:
        ids = list(account_ids or (account["id"] for account in self.store.list_accounts()))
        quote_cache = dict(quotes or {})
        updated = 0
        errors: list[dict[str, str]] = []
        now = ensure_utc(self._now())
        for account_id in ids:
            for position in self.store.list_positions(account_id):
                symbol = str(position["symbol"])
                try:
                    quote = quote_cache.get(symbol)
                    if quote is None:
                        if not fetch_missing:
                            if required_mark_session:
                                reason = f"Yahoo {required_mark_session} mark was unavailable."
                                self.store.set_position_mark_stale(account_id, symbol)
                                errors.append({"account_id": account_id, "symbol": symbol, "reason": reason})
                            continue
                        quote = self.quote_service.fetch(symbol)
                        quote_cache[symbol] = quote
                    if required_mark_session and quote.mark_session != required_mark_session:
                        reason = f"Yahoo {required_mark_session} mark was unavailable."
                        self.store.set_position_mark_stale(account_id, symbol)
                        errors.append({"account_id": account_id, "symbol": symbol, "reason": reason})
                        continue
                    if quote.mark_session == "PRE":
                        age = quote.mark_age_seconds(now)
                        if quote.mark_price is None or age is None or age > self.MAX_QUOTE_AGE_SECONDS:
                            reason = "Yahoo pre-market mark was missing or stale."
                            self.store.set_position_mark_stale(account_id, symbol)
                            errors.append({"account_id": account_id, "symbol": symbol, "reason": reason})
                            continue
                        stale = False
                    else:
                        stale = bool(self.quote_execution_block(quote, now=now))
                    self.store.update_position_mark(account_id, quote, stale=stale)
                    updated += 1
                except Exception as exc:
                    errors.append({"account_id": account_id, "symbol": symbol, "reason": str(exc)})
            self.store.record_equity_snapshot(account_id, force=False)
        return {"updated": updated, "errors": errors}

    def run_cycle(self, *, mark: bool) -> dict[str, Any]:
        """Fetch every needed symbol once, then evaluate orders and account marks."""
        session = self.session()
        market_phase = "regular" if session.is_open else "premarket" if session.is_premarket else "closed"
        can_mark_premarket = bool(mark and self.allow_premarket_marks and session.is_premarket)
        pending = self.store.pending_orders()
        can_execute_premarket = bool(
            session.is_premarket
            and any(str(order.get("execution_session") or "regular") == OrderSession.EXTENDED for order in pending)
        )
        can_execute_instant = bool(self.instant_fill and pending)
        if not session.is_open and not can_mark_premarket and not can_execute_premarket and not can_execute_instant:
            result = self.process_pending_orders(quotes={}, fetch_missing=False)
            result["market_phase"] = market_phase
            if mark:
                result["marks"] = {"updated": 0, "errors": []}
            return result
        accounts = self.store.list_accounts()
        symbols = {
            str(order["symbol"])
            for order in pending
            if session.is_open
            or self.instant_fill
            or (
                session.is_premarket
                and str(order.get("execution_session") or "regular") == OrderSession.EXTENDED
            )
        }
        if mark:
            for account in accounts:
                symbols.update(str(position["symbol"]) for position in self.store.list_positions(account["id"]))
        quotes: dict[str, PaperQuote] = {}
        fetch_errors: list[dict[str, str]] = []
        for symbol in sorted(symbols):
            try:
                quotes[symbol] = self.quote_service.fetch(symbol)
            except Exception as exc:
                fetch_errors.append({"symbol": symbol, "reason": str(exc)})
        result = self.process_pending_orders(quotes=quotes, fetch_missing=False)
        result["market_phase"] = market_phase
        result["errors"].extend(fetch_errors)
        if mark:
            result["marks"] = self.mark_accounts(
                (account["id"] for account in accounts),
                quotes=quotes,
                fetch_missing=False,
                required_mark_session="PRE" if can_mark_premarket else "",
            )
        return result

    def quote_execution_block(
        self,
        quote: PaperQuote,
        *,
        now: dt.datetime | None = None,
        market_phase: str = "regular",
    ) -> str:
        try:
            self._validate_security(quote)
        except ValueError as exc:
            return str(exc)
        if self.instant_fill:
            if quote.mark_price or quote.last_price:
                return ""
            return "Waiting for a Yahoo pre-market mark or regular last price."
        if not quote.has_executable_spread:
            return "Waiting for a valid Yahoo bid/ask spread; last price is never used for fills."
        if market_phase == "premarket":
            if quote.market_state != "PRE" or quote.mark_session != "PRE":
                return "Waiting for Yahoo to confirm an active pre-market quote."
            if quote.mark_timestamp is None:
                return "Waiting for a pre-market source timestamp from Yahoo."
            current = ensure_utc(now or self._now())
            age = max((current - ensure_utc(quote.mark_timestamp)).total_seconds(), 0.0)
        else:
            age = quote.age_seconds(now or self._now())
        if age is None:
            session_label = "pre-market " if market_phase == "premarket" else ""
            return f"Waiting for a {session_label}source timestamp from Yahoo."
        if age > self.MAX_QUOTE_AGE_SECONDS:
            session_label = " pre-market" if market_phase == "premarket" else ""
            return f"Yahoo{session_label} quote is stale ({age / 60.0:.1f} minutes old)."
        return ""

    @staticmethod
    def _instant_execution_price(
        order: dict[str, Any],
        quote: PaperQuote,
    ) -> tuple[float, float, PaperQuote] | None:
        side = OrderSide(str(order["side"]))
        order_type = OrderType(str(order["order_type"]))
        slippage = float(order["slippage_bps"] or 0.0) / 10000.0
        timestamp = quote.source_timestamp or quote.fetched_at
        if order_type is OrderType.LIMIT:
            reference = float(order["limit_price"] or 0.0)
            fill_price = reference
            source = "Virtual limit price"
        elif order_type is OrderType.STOP:
            reference = float(order["stop_price"] or 0.0)
            fill_price = reference * (1.0 + slippage if side is OrderSide.BUY else 1.0 - slippage)
            source = "Virtual stop price"
        else:
            if quote.market_state == "PRE" and quote.mark_price and quote.mark_price > 0:
                reference = float(quote.mark_price)
                timestamp = quote.mark_timestamp or quote.fetched_at
                source = f"{quote.source} (virtual PRE mark)"
            else:
                reference = float(quote.last_price or 0.0)
                source = f"{quote.source} (virtual last price)"
            fill_price = reference * (1.0 + slippage if side is OrderSide.BUY else 1.0 - slippage)
        if reference <= 0 or fill_price <= 0:
            return None
        synthetic_quote = replace(
            quote,
            bid=reference,
            ask=reference,
            source_timestamp=timestamp,
            source=source,
            mark_price=None,
            mark_timestamp=None,
            mark_session="",
        )
        return round(fill_price, 6), reference, synthetic_quote

    def _validate_security(self, quote: PaperQuote) -> None:
        if quote.symbol.strip().upper() == "":
            raise ValueError("Yahoo returned an empty symbol.")
        if quote.quote_type not in self.SUPPORTED_QUOTE_TYPES:
            raise ValueError(
                "Virtual Trading accepts US-listed stocks and ETFs only "
                f"(received type={quote.quote_type or 'missing'}, exchange={quote.exchange or 'missing'}, "
                f"currency={quote.currency or 'missing'})."
            )
        if quote.currency != "USD":
            raise ValueError(
                "Virtual Trading accepts USD securities only "
                f"(received type={quote.quote_type or 'missing'}, exchange={quote.exchange or 'missing'}, "
                f"currency={quote.currency or 'missing'})."
            )
        if quote.exchange not in self.MAJOR_US_ETF_EXCHANGES:
            raise ValueError(
                "Virtual Trading accepts stocks and ETFs listed on NYSE, Nasdaq, NYSE American, NYSE Arca, "
                f"and Cboe BZX only (received type={quote.quote_type or 'missing'}, "
                f"exchange={quote.exchange or 'missing'}, currency={quote.currency or 'missing'})."
            )

    @staticmethod
    def _execution_price(order: dict[str, Any], quote: PaperQuote) -> tuple[float, float] | None:
        side = OrderSide(str(order["side"]))
        order_type = OrderType(str(order["order_type"]))
        slippage = float(order["slippage_bps"] or 0.0) / 10000.0
        bid = float(quote.bid or 0.0)
        ask = float(quote.ask or 0.0)
        if side is OrderSide.BUY:
            reference = ask
            market_price = ask * (1.0 + slippage)
            if order_type is OrderType.LIMIT:
                limit_price = float(order["limit_price"])
                if ask > limit_price:
                    return None
                return round(min(limit_price, market_price), 6), reference
            if order_type is OrderType.STOP and ask < float(order["stop_price"]):
                return None
            return round(market_price, 6), reference
        reference = bid
        market_price = bid * (1.0 - slippage)
        if order_type is OrderType.LIMIT:
            limit_price = float(order["limit_price"])
            if bid < limit_price:
                return None
            return round(max(limit_price, market_price), 6), reference
        if order_type is OrderType.STOP and bid > float(order["stop_price"]):
            return None
        return round(market_price, 6), reference

    @staticmethod
    def _waiting_message(order: dict[str, Any], quote: PaperQuote) -> str:
        order_type = OrderType(str(order["order_type"]))
        side = OrderSide(str(order["side"]))
        if order_type is OrderType.LIMIT:
            comparator = "fall to or below" if side is OrderSide.BUY else "rise to or above"
            value = quote.ask if side is OrderSide.BUY else quote.bid
            return f"Waiting for the executable quote ({value:.4f}) to {comparator} {float(order['limit_price']):.4f}."
        if order_type is OrderType.STOP:
            comparator = "rise to or above" if side is OrderSide.BUY else "fall to or below"
            value = quote.ask if side is OrderSide.BUY else quote.bid
            return f"Waiting for the executable quote ({value:.4f}) to {comparator} {float(order['stop_price']):.4f}."
        return "Waiting for execution."
