from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..cache import CacheManager
from ..dependencies import YF_LOCK, logger, pd, yf
from .signal_models import SignalClass, SignalReason, SignalResult, TradeStatus
from .signal_scanner import (
    DEFAULT_ROLE_TIMEFRAMES,
    ScanCancelled,
    SignalMarketDataService,
    SignalScanRequest,
    SignalScannerService,
    normalize_tickers,
)


@dataclass(frozen=True)
class AutoUniverseConfig:
    """Centralized tradability filters for the automatic US-equity universe."""

    minimum_price: float = 5.0
    minimum_market_cap: float = 2_000_000_000.0
    minimum_median_dollar_volume: float = 20_000_000.0
    dollar_volume_lookback: int = 20
    source_limit: int = 100
    shortlist_limit: int = 25
    daily_history_period: str = "3mo"
    universe_cache_seconds: int = 24 * 60 * 60
    result_cache_seconds: int = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class AutoTickerCandidate:
    ticker: str
    name: str
    exchange: str
    price: float
    market_cap: float
    median_dollar_volume: float
    quality_rank: int
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AutoTickerCandidate:
        return cls(
            ticker=str(value.get("ticker") or "").upper().strip(),
            name=str(value.get("name") or value.get("ticker") or "").strip(),
            exchange=str(value.get("exchange") or "").strip(),
            price=float(value.get("price") or 0.0),
            market_cap=float(value.get("market_cap") or 0.0),
            median_dollar_volume=float(value.get("median_dollar_volume") or 0.0),
            quality_rank=max(1, int(value.get("quality_rank") or 1)),
            reasons=tuple(str(item) for item in value.get("reasons", []) if str(item).strip()),
        )


@dataclass
class AutomaticSignalScanPayload:
    candidates: list[AutoTickerCandidate]
    results: list[SignalResult]
    source: str = "Yahoo Finance"
    sourced_at: dt.datetime = field(default_factory=dt.datetime.now)
    started_at: dt.datetime = field(default_factory=dt.datetime.now)
    completed_at: dt.datetime = field(default_factory=dt.datetime.now)
    source_candidate_count: int = 0
    rejected_candidate_count: int = 0
    #: Candidates that cleared every tradability filter, before the shortlist cut. Reported apart
    #: from ``rejected_candidate_count`` so the shortlist truncation is not presented as rejection.
    passed_filter_count: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    universe_from_cache: bool = False


class AutomaticTickerUniverseService:
    """Source and rank liquid US common equities without user-entered symbols."""

    _MAJOR_EXCHANGES = ("NYQ", "NMS", "NGM", "NCM", "ASE")
    _EXCHANGE_LABELS = {
        "NYQ": "NYSE",
        "NMS": "Nasdaq",
        "NGM": "Nasdaq",
        "NCM": "Nasdaq",
        "ASE": "NYSE American",
    }
    _CACHE_NAMESPACE = "signal_scanner2_universe"
    _CACHE_KEY = "liquid_us_v1"

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        *,
        config: AutoUniverseConfig | None = None,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.cache_manager = cache_manager or CacheManager()
        self.config = config or AutoUniverseConfig()
        self._now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    def source_candidates(self, *, force_refresh: bool = False) -> dict[str, Any]:
        today = self._now().astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if not force_refresh:
            cached = self.cache_manager.get_json_payload(
                self._CACHE_NAMESPACE,
                self._CACHE_KEY,
                max_age_seconds=self.config.universe_cache_seconds,
            )
            if isinstance(cached, dict) and cached.get("session_date") == today:
                return {
                    **cached,
                    "candidates": [
                        AutoTickerCandidate.from_dict(item)
                        for item in cached.get("candidates", [])
                        if isinstance(item, dict)
                    ],
                    "from_cache": True,
                }

        quotes = self._screen_quotes()
        rows = [row for row in (self._quote_row(quote) for quote in quotes) if row is not None]
        rows_by_ticker = {str(row["ticker"]): row for row in rows}
        daily_frames = self._download_daily_frames(list(rows_by_ticker))
        candidates: list[AutoTickerCandidate] = []
        rejected = max(0, len(quotes) - len(rows_by_ticker))
        session_date = dt.date.fromisoformat(today)
        for ticker, row in rows_by_ticker.items():
            dollar_volume = self._median_completed_dollar_volume(daily_frames.get(ticker), session_date)
            if dollar_volume is None or dollar_volume < self.config.minimum_median_dollar_volume:
                rejected += 1
                continue
            candidates.append(AutoTickerCandidate(
                ticker=ticker,
                name=str(row["name"]),
                exchange=str(row["exchange"]),
                price=float(row["price"]),
                market_cap=float(row["market_cap"]),
                median_dollar_volume=float(dollar_volume),
                quality_rank=1,
                reasons=(
                    f"Market cap ${float(row['market_cap']) / 1_000_000_000:.1f}B",
                    f"20-session median dollar volume ${float(dollar_volume) / 1_000_000:.1f}M",
                    f"Listed on {row['exchange']}",
                ),
            ))
        ranked = sorted(
            candidates,
            key=lambda item: (-item.median_dollar_volume, -item.market_cap, item.ticker),
        )[: self.config.shortlist_limit]
        ranked = [
            AutoTickerCandidate(**{**asdict(candidate), "quality_rank": rank})
            for rank, candidate in enumerate(ranked, start=1)
        ]
        sourced_at = self._now().isoformat()
        payload = {
            "candidates": [candidate.to_dict() for candidate in ranked],
            "source": "Yahoo Finance",
            "sourced_at": sourced_at,
            "session_date": today,
            "source_candidate_count": len(quotes),
            # Rejection counts only what failed a filter. Candidates dropped by the shortlist cut
            # are healthy names that simply ranked below the limit, and reporting them as rejected
            # made the universe look far more selective than it is.
            "rejected_candidate_count": rejected,
            "passed_filter_count": len(candidates),
        }
        self.cache_manager.save_json_payload(self._CACHE_NAMESPACE, self._CACHE_KEY, payload)
        return {**payload, "candidates": ranked, "from_cache": False}

    def _query(self) -> Any:
        exchange_query = yf.EquityQuery(
            "or",
            [yf.EquityQuery("eq", ["exchange", exchange]) for exchange in self._MAJOR_EXCHANGES],
        )
        return yf.EquityQuery("and", [
            yf.EquityQuery("eq", ["region", "us"]),
            yf.EquityQuery("gte", ["intradayprice", self.config.minimum_price]),
            yf.EquityQuery("gte", ["intradaymarketcap", self.config.minimum_market_cap]),
            exchange_query,
        ])

    def _screen_quotes(self) -> list[dict[str, Any]]:
        logger.info("Sourcing automatic signal universe from Yahoo Finance")
        with YF_LOCK:
            response = yf.screen(
                self._query(),
                size=self.config.source_limit,
                offset=0,
                sortField="intradaymarketcap",
                sortAsc=False,
            )
        quotes = response.get("quotes", []) if isinstance(response, dict) else []
        return [quote for quote in quotes if isinstance(quote, dict)]

    def _quote_row(self, quote: Mapping[str, Any]) -> dict[str, Any] | None:
        if str(quote.get("quoteType") or "").upper().strip() != "EQUITY":
            return None
        exchange = str(quote.get("exchange") or "").upper().strip()
        if exchange not in self._MAJOR_EXCHANGES:
            return None
        ticker = str(quote.get("symbol") or "").upper().strip()
        price = self._first_positive(quote.get("regularMarketPrice"), quote.get("intradayprice"))
        market_cap = self._first_positive(quote.get("marketCap"), quote.get("intradaymarketcap"))
        if not ticker or price is None or market_cap is None:
            return None
        if price < self.config.minimum_price or market_cap < self.config.minimum_market_cap:
            return None
        return {
            "ticker": ticker,
            "name": str(quote.get("longName") or quote.get("shortName") or ticker).strip(),
            "exchange": self._EXCHANGE_LABELS.get(exchange, exchange),
            "price": price,
            "market_cap": market_cap,
        }

    def _download_daily_frames(self, tickers: Sequence[str]) -> dict[str, pd.DataFrame]:
        symbols = normalize_tickers(tickers, limit=max(len(tickers), 1))
        if not symbols:
            return {}
        logger.info("Fetching daily liquidity history for %s automatic candidates", len(symbols))
        with YF_LOCK:
            frame = yf.download(
                symbols,
                period=self.config.daily_history_period,
                interval="1d",
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=True,
                group_by="column",
            )
        return SignalMarketDataService.split_download_frame(frame, symbols)

    def _median_completed_dollar_volume(
        self,
        frame: Any,
        session_date: dt.date,
    ) -> float | None:
        if frame is None or getattr(frame, "empty", True):
            return None
        required = {"Close", "Volume"}
        if not required.issubset(set(frame.columns)):
            return None
        working = frame[["Close", "Volume"]].copy()
        dates = pd.to_datetime(working.index, errors="coerce")
        try:
            if getattr(dates, "tz", None) is not None:
                dates = dates.tz_convert("America/New_York").tz_localize(None)
        except (TypeError, ValueError):
            pass
        completed_mask = pd.Series(dates.date < session_date, index=working.index)
        working = working.loc[completed_mask.to_numpy()]
        close = pd.to_numeric(working["Close"], errors="coerce")
        volume = pd.to_numeric(working["Volume"], errors="coerce")
        values = (close * volume).replace([float("inf"), float("-inf")], float("nan")).dropna()
        values = values[values > 0].iloc[-self.config.dollar_volume_lookback :]
        if len(values) < self.config.dollar_volume_lookback:
            return None
        value = float(values.median())
        return value if math.isfinite(value) and value > 0 else None

    @staticmethod
    def _first_positive(*values: Any) -> float | None:
        for value in values:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric) and numeric > 0:
                return numeric
        return None


class AutomaticSignalScannerService:
    """Run universe selection and the reusable signal engine as one scan."""

    _RESULT_NAMESPACE = "signal_scanner2_results"
    #: Bumped when the scoring scale changed from 0-10 to 0-100. A cached v1 payload holds scores
    #: that would render as if they were out of 100, so the old key must not be read back.
    _RESULT_CACHE_KEY = "latest_v2"

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        *,
        universe_service: AutomaticTickerUniverseService | None = None,
        scanner_service: SignalScannerService | None = None,
        config: AutoUniverseConfig | None = None,
    ) -> None:
        self.cache_manager = cache_manager or CacheManager()
        self.config = config or AutoUniverseConfig()
        self.universe_service = universe_service or AutomaticTickerUniverseService(
            self.cache_manager,
            config=self.config,
        )
        self.scanner_service = scanner_service or SignalScannerService(
            SignalMarketDataService(self.cache_manager)
        )

    def run_scan(
        self,
        *,
        force_universe_refresh: bool = False,
        force_market_refresh: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> AutomaticSignalScanPayload:
        started_at = dt.datetime.now()
        if cancel is not None and cancel():
            raise ScanCancelled("Signal scan cancelled")
        universe = self.universe_service.source_candidates(force_refresh=force_universe_refresh)
        candidates = list(universe.get("candidates") or [])
        if not candidates:
            raise ValueError("No liquid US equities passed the automatic universe filters")
        tickers = tuple(candidate.ticker for candidate in candidates)
        request = SignalScanRequest(
            tickers=tickers,
            role_timeframes=DEFAULT_ROLE_TIMEFRAMES,
            force_refresh=force_market_refresh,
        )
        results, errors = self.scanner_service.scan_tickers_batched(
            request, progress=progress, cancel=cancel
        )
        payload = AutomaticSignalScanPayload(
            candidates=candidates,
            results=results,
            source=str(universe.get("source") or "Yahoo Finance"),
            sourced_at=self._parse_datetime(universe.get("sourced_at")) or started_at,
            started_at=started_at,
            completed_at=dt.datetime.now(),
            source_candidate_count=int(universe.get("source_candidate_count") or 0),
            rejected_candidate_count=int(universe.get("rejected_candidate_count") or 0),
            passed_filter_count=int(universe.get("passed_filter_count") or len(candidates)),
            errors=errors,
            universe_from_cache=bool(universe.get("from_cache", False)),
        )
        self.save_latest_payload(payload)
        return payload

    def save_latest_payload(self, payload: AutomaticSignalScanPayload) -> None:
        self.cache_manager.save_json_payload(
            self._RESULT_NAMESPACE,
            self._RESULT_CACHE_KEY,
            self.payload_to_dict(payload),
        )

    def load_latest_payload(self) -> AutomaticSignalScanPayload | None:
        value = self.cache_manager.get_json_payload(
            self._RESULT_NAMESPACE,
            self._RESULT_CACHE_KEY,
            max_age_seconds=self.config.result_cache_seconds,
            allow_stale=False,
        )
        return self.payload_from_dict(value) if isinstance(value, dict) else None

    @classmethod
    def payload_to_dict(cls, payload: AutomaticSignalScanPayload) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in payload.candidates],
            "results": [cls.signal_result_to_dict(result) for result in payload.results],
            "source": payload.source,
            "sourced_at": payload.sourced_at.isoformat(),
            "started_at": payload.started_at.isoformat(),
            "completed_at": payload.completed_at.isoformat(),
            "source_candidate_count": payload.source_candidate_count,
            "rejected_candidate_count": payload.rejected_candidate_count,
            "passed_filter_count": payload.passed_filter_count,
            "errors": dict(payload.errors),
            "universe_from_cache": payload.universe_from_cache,
        }

    @classmethod
    def payload_from_dict(cls, value: Mapping[str, Any]) -> AutomaticSignalScanPayload:
        return AutomaticSignalScanPayload(
            candidates=[
                AutoTickerCandidate.from_dict(item)
                for item in value.get("candidates", [])
                if isinstance(item, Mapping)
            ],
            results=[
                cls.signal_result_from_dict(item)
                for item in value.get("results", [])
                if isinstance(item, Mapping)
            ],
            source=str(value.get("source") or "Yahoo Finance"),
            sourced_at=cls._parse_datetime(value.get("sourced_at")) or dt.datetime.now(),
            started_at=cls._parse_datetime(value.get("started_at")) or dt.datetime.now(),
            completed_at=cls._parse_datetime(value.get("completed_at")) or dt.datetime.now(),
            source_candidate_count=int(value.get("source_candidate_count") or 0),
            rejected_candidate_count=int(value.get("rejected_candidate_count") or 0),
            passed_filter_count=int(value.get("passed_filter_count") or 0),
            errors={str(key): str(item) for key, item in dict(value.get("errors") or {}).items()},
            universe_from_cache=bool(value.get("universe_from_cache", False)),
        )

    @staticmethod
    def signal_result_to_dict(result: SignalResult) -> dict[str, Any]:
        return {
            "ticker": result.ticker,
            "timestamp": result.timestamp.isoformat(),
            "price": result.price,
            "raw_score": result.raw_score,
            "max_score": result.max_score,
            "trend_score": result.trend_score,
            "trend_max_score": result.trend_max_score,
            "momentum_score": result.momentum_score,
            "momentum_max_score": result.momentum_max_score,
            "volume_score": result.volume_score,
            "volume_max_score": result.volume_max_score,
            "entry_score": result.entry_score,
            "entry_max_score": result.entry_max_score,
            "relative_score": result.relative_score,
            "relative_max_score": result.relative_max_score,
            "signal": result.signal.value,
            "trade_status": result.trade_status.value,
            "reasons": [asdict(reason) for reason in result.reasons],
            "warnings": list(result.warnings),
            "indicators": dict(result.indicators),
            "timeframe_status": dict(result.timeframe_status),
            "timeframe_bars": {
                str(role): dict(entry)
                for role, entry in dict(result.timeframe_bars).items()
                if isinstance(entry, Mapping)
            },
            "error": result.error,
        }

    @classmethod
    def signal_result_from_dict(cls, value: Mapping[str, Any]) -> SignalResult:
        reason_fields = set(SignalReason.__dataclass_fields__)
        return SignalResult(
            ticker=str(value.get("ticker") or "").upper().strip(),
            timestamp=cls._parse_datetime(value.get("timestamp")) or dt.datetime.now(),
            price=cls._optional_float(value.get("price")),
            raw_score=float(value.get("raw_score") or 0.0),
            max_score=float(value.get("max_score") or 0.0),
            trend_score=float(value.get("trend_score") or 0.0),
            trend_max_score=float(value.get("trend_max_score") or 0.0),
            momentum_score=float(value.get("momentum_score") or 0.0),
            momentum_max_score=float(value.get("momentum_max_score") or 0.0),
            volume_score=float(value.get("volume_score") or 0.0),
            volume_max_score=float(value.get("volume_max_score") or 0.0),
            entry_score=float(value.get("entry_score") or 0.0),
            entry_max_score=float(value.get("entry_max_score") or 0.0),
            relative_score=float(value.get("relative_score") or 0.0),
            relative_max_score=float(value.get("relative_max_score") or 0.0),
            signal=SignalClass(str(value.get("signal") or SignalClass.NONE.value)),
            trade_status=TradeStatus(str(value.get("trade_status") or TradeStatus.NONE.value)),
            reasons=[
                SignalReason(**{key: item[key] for key in reason_fields if key in item})
                for item in value.get("reasons", [])
                if isinstance(item, Mapping)
            ],
            warnings=[str(item) for item in value.get("warnings", [])],
            indicators=dict(value.get("indicators") or {}),
            timeframe_status={str(key): str(item) for key, item in dict(value.get("timeframe_status") or {}).items()},
            timeframe_bars={
                str(key): {
                    "as_of": (str(item.get("as_of")) if item.get("as_of") else None),
                    "partial": bool(item.get("partial", False)),
                    "dropped": bool(item.get("dropped", False)),
                }
                for key, item in dict(value.get("timeframe_bars") or {}).items()
                if isinstance(item, Mapping)
            },
            error=str(value.get("error") or ""),
        )

    @staticmethod
    def _parse_datetime(value: Any) -> dt.datetime | None:
        try:
            return dt.datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None
