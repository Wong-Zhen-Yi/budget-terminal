from __future__ import annotations

import datetime
import math
import time
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - older Python / missing tzdata fallback
    ZoneInfo = None

from ..cache import CacheManager
from ..data_service.results import attach_market_data_result, make_market_data_error, make_market_data_meta, market_data_errors, market_data_meta
from ..data_service.tasks import MarketDataTaskRunner
from ..dependencies import YF_LOCK, logger, pd, yf


def _options_market_timezone() -> datetime.tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/New_York")
        except Exception:
            pass
    return datetime.timezone(datetime.timedelta(hours=-5))


OPTIONS_MARKET_TIMEZONE = _options_market_timezone()


class OptionsMarketDataService:
    """Fetch options expiries, chains, and quote rows with cache fallback metadata."""

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        *,
        expiry_memory_cache: dict[str, tuple[float, list[str]]] | None = None,
        chain_memory_cache: dict[tuple[str, str], tuple[float, Any]] | None = None,
        expiry_memory_ttl_seconds: float = 900.0,
        chain_memory_ttl_seconds: float = 60.0,
        task_runner: MarketDataTaskRunner | None = None,
    ) -> None:
        self.cache_manager = cache_manager or CacheManager()
        self.expiry_memory_cache = expiry_memory_cache if expiry_memory_cache is not None else {}
        self.chain_memory_cache = chain_memory_cache if chain_memory_cache is not None else {}
        self.expiry_memory_ttl_seconds = float(expiry_memory_ttl_seconds)
        self.chain_memory_ttl_seconds = float(chain_memory_ttl_seconds)
        self.task_runner = task_runner or MarketDataTaskRunner(default_timeout_seconds=60.0, default_retries=1)

    def fetch_expiries_payload(self, ticker: Any) -> dict[str, Any]:
        ticker_key = str(ticker or "").strip().upper()
        if not ticker_key:
            return attach_market_data_result(
                {"expiries": []},
                meta=make_market_data_meta(source="input", freshness="failed", failure_reason="No ticker was provided."),
            )
        now = time.time()
        cached_memory = self.expiry_memory_cache.get(ticker_key)
        if cached_memory and (now - cached_memory[0]) < self.expiry_memory_ttl_seconds:
            expiry_list = self._filter_live_expiries(cached_memory[1])
            if expiry_list:
                self.expiry_memory_cache[ticker_key] = (cached_memory[0], list(expiry_list))
                return attach_market_data_result(
                    {"expiries": expiry_list},
                    meta=make_market_data_meta(source="memory cache", freshness="fresh", cache_age_seconds=now - cached_memory[0]),
                )
            self.expiry_memory_cache.pop(ticker_key, None)
        cached = self.cache_manager.get_options_expiries(ticker_key, return_metadata=True)
        if cached:
            expiries, cache_meta = cached
            expiry_list = self._filter_live_expiries(expiries)
            if expiry_list:
                self.expiry_memory_cache[ticker_key] = (now, list(expiry_list))
                self.cache_manager.save_options_expiries(ticker_key, expiry_list)
                return attach_market_data_result(
                    {"expiries": expiry_list},
                    meta=make_market_data_meta(
                        source="cache",
                        freshness="fresh",
                        cache_age_seconds=(cache_meta or {}).get("cache_age_seconds") if isinstance(cache_meta, dict) else None,
                    ),
                )
        stale_cached = self.cache_manager.get_options_expiries(ticker_key, allow_stale=True, return_metadata=True)
        stale_expiries = self._filter_live_expiries(stale_cached[0]) if stale_cached else []
        stale_meta = stale_cached[1] if stale_cached and isinstance(stale_cached[1], dict) else {}

        def fetch_expiries() -> list[str]:
            with YF_LOCK:
                expiries = self._filter_live_expiries(yf.Ticker(ticker_key).options)
            if not expiries:
                raise ValueError(f"No current option expiries returned for {ticker_key}.")
            self.cache_manager.save_options_expiries(ticker_key, expiries)
            self.expiry_memory_cache[ticker_key] = (time.time(), list(expiries))
            return list(expiries)

        result = self.task_runner.run(
            f"options_expiries:{ticker_key}",
            fetch_expiries,
            source="yfinance",
            cache_fallback=(lambda: stale_expiries) if stale_expiries else None,
            cache_age_seconds=stale_meta.get("cache_age_seconds"),
            success_check=lambda values: bool(values),
            failure_reason=f"No current option expiries returned for {ticker_key}.",
        )
        return attach_market_data_result({"expiries": self._filter_live_expiries(result.data or [])}, meta=result.meta, errors=result.errors)

    def fetch_chain_payload(self, ticker: Any, expiry: Any) -> dict[str, Any]:
        ticker_key = str(ticker or "").strip().upper()
        expiry_key = str(expiry or "").strip()
        if not ticker_key or not expiry_key:
            return attach_market_data_result(
                {"chain": pd.DataFrame()},
                meta=make_market_data_meta(source="input", freshness="failed", failure_reason="Ticker and expiry are required."),
            )
        if self._is_past_expiry(expiry_key):
            return attach_market_data_result(
                {"chain": pd.DataFrame()},
                meta=make_market_data_meta(
                    source="input",
                    freshness="failed",
                    failure_reason=f"Option expiry {expiry_key} has passed.",
                ),
            )
        now = time.time()
        cache_key = (ticker_key, expiry_key)
        cached_memory = self.chain_memory_cache.get(cache_key)
        if cached_memory and (now - cached_memory[0]) < self.chain_memory_ttl_seconds:
            return attach_market_data_result(
                {"chain": cached_memory[1].copy()},
                meta=make_market_data_meta(source="memory cache", freshness="fresh", cache_age_seconds=now - cached_memory[0]),
            )
        cached = self.cache_manager.get_options_chain(ticker_key, expiry_key, return_metadata=True)
        if cached:
            chain_df, cache_meta = cached
            chain_df = chain_df.copy()
            self._normalize_chain_columns(chain_df, ticker_key, expiry_key)
            if chain_df is not None and not chain_df.empty:
                self.chain_memory_cache[cache_key] = (now, chain_df.copy())
                return attach_market_data_result(
                    {"chain": chain_df},
                    meta=make_market_data_meta(
                        source="cache",
                        freshness="fresh",
                        cache_age_seconds=(cache_meta or {}).get("cache_age_seconds") if isinstance(cache_meta, dict) else None,
                    ),
                )
        stale_cached = self.cache_manager.get_options_chain(ticker_key, expiry_key, allow_stale=True, return_metadata=True)
        stale_df = stale_cached[0].copy() if stale_cached else None
        stale_meta = stale_cached[1] if stale_cached and isinstance(stale_cached[1], dict) else {}
        if stale_df is not None:
            self._normalize_chain_columns(stale_df, ticker_key, expiry_key)

        def fetch_chain() -> Any:
            with YF_LOCK:
                chain = yf.Ticker(ticker_key).option_chain(expiry_key)
            calls = chain.calls.copy()
            puts = chain.puts.copy()
            calls["type"] = "Call"
            puts["type"] = "Put"
            chain_df = pd.concat([calls, puts], ignore_index=True)
            if chain_df is None or chain_df.empty:
                raise ValueError(f"No option chain returned for {ticker_key} {expiry_key}.")
            self._normalize_chain_columns(chain_df, ticker_key, expiry_key)
            self.cache_manager.save_options_chain(ticker_key, expiry_key, chain_df)
            self.chain_memory_cache[cache_key] = (time.time(), chain_df.copy())
            return chain_df

        result = self.task_runner.run(
            f"options_chain:{ticker_key}:{expiry_key}",
            fetch_chain,
            source="yfinance",
            cache_fallback=(lambda: stale_df) if stale_df is not None and not stale_df.empty else None,
            cache_age_seconds=stale_meta.get("cache_age_seconds"),
            success_check=lambda frame: frame is not None and not getattr(frame, "empty", True),
            failure_reason=f"No option chain returned for {ticker_key} {expiry_key}.",
        )
        chain = result.data if result.data is not None and not isinstance(result.data, dict) else pd.DataFrame()
        return attach_market_data_result({"chain": chain}, meta=result.meta, errors=result.errors)

    def fetch_option_quote_payload(
        self,
        ticker: Any,
        expiry: Any,
        strike: Any,
        strategy: Any,
        *,
        underlying_price: Any = 0.0,
    ) -> dict[str, Any]:
        ticker_key = str(ticker or "").strip().upper()
        expiry_key = str(expiry or "").strip()
        if not expiry_key:
            return attach_market_data_result(
                {"error": "Incomplete Data"},
                meta=make_market_data_meta(source="input", freshness="failed", failure_reason="Option expiry is missing."),
            )
        if self._is_past_expiry(expiry_key):
            return attach_market_data_result(
                {"error": "Expired"},
                meta=make_market_data_meta(
                    source="input",
                    freshness="failed",
                    failure_reason=f"Option expiry {expiry_key} has passed.",
                ),
            )
        chain_payload = self.fetch_chain_payload(ticker_key, expiry_key)
        chain_df = chain_payload.get("chain") if isinstance(chain_payload, dict) else None
        if chain_df is None or getattr(chain_df, "empty", True):
            return attach_market_data_result(
                {"error": "No Data"},
                meta=market_data_meta(chain_payload),
                errors=market_data_errors(chain_payload),
            )
        try:
            target_strike = self._clean_number(strike)
            is_call = "Call" in str(strategy or "") or str(strategy or "") == "Calls"
            option_type = "Call" if is_call else "Put"
            frame = chain_df[chain_df.get("type", "") == option_type].copy() if "type" in chain_df.columns else chain_df
            if frame.empty:
                raise ValueError(f"No {option_type.lower()} rows returned.")
            strikes = pd.to_numeric(frame["strike"], errors="coerce")
            if target_strike <= 0:
                underlying = self._clean_number(underlying_price)
                diffs = (strikes - underlying).abs() if underlying > 0 else strikes.abs()
            else:
                diffs = (strikes - target_strike).abs()
            valid_diffs = diffs.dropna()
            if valid_diffs.empty:
                raise LookupError("Strike Not Found")
            match = frame.loc[[valid_diffs.idxmin()]]
            if match.empty:
                raise LookupError("Strike Not Found")
            row = match.iloc[0]
            actual_strike = float(row.get("strike", 0.0) or 0.0)
            bid = self._clean_number(row.get("bid", 0.0))
            ask = self._clean_number(row.get("ask", 0.0))
            last = self._clean_number(row.get("lastPrice", 0.0))
            price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
            payload = {
                "price": price,
                "iv": self._clean_number(row.get("impliedVolatility", 0.0)),
                "delta": self._clean_number(row.get("delta", 0.0)) if "delta" in row else None,
                "strike": actual_strike,
                "volume": self._clean_number(row.get("volume", 0.0)),
                "open_interest": self._clean_number(row.get("openInterest", row.get("open_interest", 0.0))),
            }
            return attach_market_data_result(payload, meta=market_data_meta(chain_payload), errors=market_data_errors(chain_payload))
        except LookupError as exc:
            return self._quote_error_payload("Strike Not Found", chain_payload, exc)
        except Exception as exc:
            message = str(exc)
            if "expired" in message.lower():
                label = "Expired"
            elif "not found" in message.lower():
                label = "Ticker Err"
            else:
                label = "Fetch Err"
            return self._quote_error_payload(label, chain_payload, exc)

    def _quote_error_payload(self, label: str, chain_payload: Any, exc: Exception) -> dict[str, Any]:
        errors = [
            *market_data_errors(chain_payload),
            make_market_data_error(source="yfinance/cache", reason=str(exc) or label, operation="option_quote", exception=exc),
        ]
        meta = market_data_meta(chain_payload)
        meta["freshness"] = "failed"
        meta["is_stale"] = False
        meta["is_partial"] = False
        meta["failure_reason"] = str(exc) or label
        return attach_market_data_result({"error": label}, meta=meta, errors=errors)

    def _normalize_chain_columns(self, chain_df: Any, ticker: str, expiry: str) -> None:
        if chain_df is None:
            return
        if "ticker" not in chain_df.columns:
            chain_df["ticker"] = ticker
        if "expiration" not in chain_df.columns:
            chain_df["expiration"] = expiry
        if "type" not in chain_df.columns:
            chain_df["type"] = ""

    def _is_past_expiry(self, expiry: Any) -> bool:
        """Return True when an ISO option expiration date has passed in the US market timezone."""
        try:
            expiry_date = datetime.date.fromisoformat(str(expiry or "").strip())
        except ValueError:
            return False
        market_today = datetime.datetime.now(OPTIONS_MARKET_TIMEZONE).date()
        return expiry_date < market_today

    def _filter_live_expiries(self, expiries: Any) -> list[str]:
        """Return unique non-expired expiry strings, preserving source order."""
        live_expiries: list[str] = []
        seen: set[str] = set()
        for expiry in list(expiries or []):
            expiry_text = str(expiry or "").strip()
            if not expiry_text or expiry_text in seen or self._is_past_expiry(expiry_text):
                continue
            seen.add(expiry_text)
            live_expiries.append(expiry_text)
        return live_expiries

    def _clean_number(self, value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(number) or math.isinf(number):
            return default
        return number
