from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..cache import CacheManager
from ..dependencies import YF_LOCK, logger, pd, yf
from .signal_engine import SignalConfig, SignalResult, TrendBreakoutStrategy, data_error_result


@dataclass(frozen=True)
class TimeframeRequest:
    label: str
    interval: str
    period: str
    cache_max_age_hours: float


TIMEFRAME_REQUESTS: dict[str, TimeframeRequest] = {
    "1 Week": TimeframeRequest("1 Week", "1wk", "10y", 12.0),
    "1 Day": TimeframeRequest("1 Day", "1d", "2y", 4.0),
    "1 Hour": TimeframeRequest("1 Hour", "1h", "6mo", 0.25),
    "30 Minutes": TimeframeRequest("30 Minutes", "30m", "60d", 0.10),
    "15 Minutes": TimeframeRequest("15 Minutes", "15m", "60d", 0.05),
    "5 Minutes": TimeframeRequest("5 Minutes", "5m", "30d", 2.0 / 60.0),
    "1 Minute": TimeframeRequest("1 Minute", "1m", "7d", 45.0 / 3600.0),
}

DEFAULT_ROLE_TIMEFRAMES = {
    "trend": "1 Day",
    "momentum": "1 Hour",
    "setup": "5 Minutes",
    "entry": "1 Minute",
}


@dataclass(frozen=True)
class SignalScanRequest:
    tickers: tuple[str, ...]
    role_timeframes: Mapping[str, str]
    config: SignalConfig = SignalConfig()
    force_refresh: bool = False


def normalize_tickers(values: Any, *, limit: int = 50) -> list[str]:
    if isinstance(values, str):
        raw_values = values.replace("\n", ",").replace(";", ",").split(",")
    else:
        raw_values = list(values or [])
    tickers = []
    for value in raw_values:
        ticker = str(value or "").upper().strip()
        if not ticker or ticker in tickers:
            continue
        if not all(character.isalnum() or character in {".", "-", "^", "="} for character in ticker):
            continue
        tickers.append(ticker)
        if len(tickers) >= max(1, int(limit)):
            break
    return tickers


class SignalMarketDataService:
    """Fetch and cache the OHLCV frames required by signal strategies."""

    source_name = "Yahoo Finance"

    def __init__(self, cache_manager: CacheManager | None = None) -> None:
        self.cache_manager = cache_manager or CacheManager()

    @staticmethod
    def timeframe_request(label: Any) -> TimeframeRequest:
        label_text = str(label or "").strip()
        request = TIMEFRAME_REQUESTS.get(label_text)
        if request is None:
            raise ValueError(f"Unsupported signal timeframe: {label_text or 'blank'}")
        return request

    @staticmethod
    def _cache_interval(request: TimeframeRequest) -> str:
        return f"signal_{request.interval}"

    def fetch_frame(
        self,
        ticker: str,
        request: TimeframeRequest,
        *,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        cache_interval = self._cache_interval(request)
        if not force_refresh:
            cached = self.cache_manager.get_data(
                ticker,
                cache_interval,
                max_age_hours=request.cache_max_age_hours,
            )
            if cached is not None and not getattr(cached, "empty", True):
                logger.info("Signal scanner cache hit: %s %s", ticker, request.interval)
                return cached.copy()

        logger.info("Fetching signal data: %s %s (%s)", ticker, request.interval, request.period)
        with YF_LOCK:
            frame = yf.download(
                ticker,
                period=request.period,
                interval=request.interval,
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=False,
            )
        if frame is None or getattr(frame, "empty", True):
            raise ValueError(f"No {request.label} history returned")
        self.cache_manager.save_data(ticker, cache_interval, frame)
        return frame.copy()

    def fetch_frames(
        self,
        tickers: Sequence[str],
        request: TimeframeRequest,
        *,
        force_refresh: bool = False,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        """Fetch one timeframe for many symbols, batching only cache misses."""

        symbols = normalize_tickers(tickers, limit=max(len(tickers), 1))
        frames: dict[str, pd.DataFrame] = {}
        errors: dict[str, str] = {}
        missing: list[str] = []
        cache_interval = self._cache_interval(request)
        for ticker in symbols:
            if not force_refresh:
                cached = self.cache_manager.get_data(
                    ticker,
                    cache_interval,
                    max_age_hours=request.cache_max_age_hours,
                )
                if cached is not None and not getattr(cached, "empty", True):
                    frames[ticker] = cached.copy()
                    continue
            missing.append(ticker)

        if not missing:
            return frames, errors
        if len(missing) == 1:
            ticker = missing[0]
            try:
                frames[ticker] = self.fetch_frame(ticker, request, force_refresh=True)
            except Exception as exc:
                errors[ticker] = str(exc)
            return frames, errors

        logger.info(
            "Fetching batched signal data: %s ticker(s) %s (%s)",
            len(missing),
            request.interval,
            request.period,
        )
        try:
            with YF_LOCK:
                batch = yf.download(
                    missing,
                    period=request.period,
                    interval=request.interval,
                    auto_adjust=False,
                    prepost=False,
                    progress=False,
                    threads=True,
                    group_by="column",
                )
            split = self.split_download_frame(batch, missing)
        except Exception as exc:
            logger.warning("Batched signal fetch failed for %s: %s", request.interval, exc)
            split = {}

        for ticker, frame in split.items():
            if frame is None or getattr(frame, "empty", True):
                continue
            frames[ticker] = frame.copy()
            self.cache_manager.save_data(ticker, cache_interval, frame)

        for ticker in missing:
            if ticker in frames:
                continue
            try:
                frames[ticker] = self.fetch_frame(ticker, request, force_refresh=True)
            except Exception as exc:
                errors[ticker] = str(exc)
        return frames, errors

    @staticmethod
    def split_download_frame(frame: Any, tickers: Sequence[str]) -> dict[str, pd.DataFrame]:
        """Split either yfinance multi-index column orientation into ticker frames."""

        if frame is None or getattr(frame, "empty", True):
            return {}
        symbols = normalize_tickers(tickers, limit=max(len(tickers), 1))
        if not isinstance(frame.columns, pd.MultiIndex):
            return {symbols[0]: frame.dropna(how="all").copy()} if len(symbols) == 1 else {}
        output: dict[str, pd.DataFrame] = {}
        for ticker in symbols:
            selected = None
            for level in range(frame.columns.nlevels):
                values = {str(value).upper() for value in frame.columns.get_level_values(level)}
                if ticker not in values:
                    continue
                try:
                    selected = frame.xs(ticker, axis=1, level=level, drop_level=True)
                except (KeyError, TypeError):
                    selected = None
                if selected is not None:
                    break
            if selected is None:
                continue
            if isinstance(selected, pd.Series):
                selected = selected.to_frame()
            selected = selected.dropna(how="all")
            if not selected.empty:
                output[ticker] = selected.copy()
        return output


class SignalScannerService:
    """Coordinate market-data collection and strategy evaluation per ticker."""

    _ROLES = ("trend", "momentum", "setup", "entry")

    def __init__(
        self,
        data_service: SignalMarketDataService | None = None,
        *,
        strategy: TrendBreakoutStrategy | None = None,
    ) -> None:
        self.data_service = data_service or SignalMarketDataService()
        self.strategy = strategy

    def scan_ticker(self, ticker: Any, request: SignalScanRequest) -> SignalResult:
        symbol = normalize_tickers([ticker], limit=1)
        if not symbol:
            return data_error_result(str(ticker or ""), "Invalid ticker", request.config)
        ticker_text = symbol[0]
        frames: dict[str, pd.DataFrame] = {}
        fetch_errors: dict[str, str] = {}
        fetched_by_interval: dict[str, pd.DataFrame] = {}
        for role in self._ROLES:
            timeframe_label = request.role_timeframes.get(role, DEFAULT_ROLE_TIMEFRAMES[role])
            try:
                timeframe = self.data_service.timeframe_request(timeframe_label)
                if timeframe.interval not in fetched_by_interval:
                    fetched_by_interval[timeframe.interval] = self.data_service.fetch_frame(
                        ticker_text,
                        timeframe,
                        force_refresh=request.force_refresh,
                    )
                frames[role] = fetched_by_interval[timeframe.interval]
            except Exception as exc:
                fetch_errors[role] = str(exc)
                frames[role] = pd.DataFrame()
                logger.info("Signal scanner %s %s data failed: %s", ticker_text, role, exc)

        strategy = self.strategy or TrendBreakoutStrategy(request.config)
        try:
            result = strategy.evaluate(ticker_text, frames)
        except Exception as exc:
            logger.exception("Signal calculation failed for %s", ticker_text)
            return data_error_result(ticker_text, f"Signal calculation failed: {exc}", request.config)
        for role, message in fetch_errors.items():
            detail = f"{role.title()} data: {message}"
            if detail not in result.warnings:
                result.warnings.append(detail)
            result.timeframe_status[role] = message
        logger.info(
            "%s signal score: %.1f/%.1f, signal=%s, trade_status=%s",
            ticker_text,
            result.raw_score,
            result.max_score,
            result.signal.value,
            result.trade_status.value,
        )
        return result

    def scan_tickers_batched(
        self,
        request: SignalScanRequest,
        *,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[SignalResult], dict[str, str]]:
        """Evaluate a ticker collection after batched timeframe collection."""

        tickers = normalize_tickers(request.tickers, limit=max(len(request.tickers), 1))
        frames_by_ticker: dict[str, dict[str, pd.DataFrame]] = {ticker: {} for ticker in tickers}
        errors_by_ticker: dict[str, list[str]] = {ticker: [] for ticker in tickers}
        fetched_by_interval: dict[str, tuple[dict[str, pd.DataFrame], dict[str, str]]] = {}
        for role in self._ROLES:
            label = request.role_timeframes.get(role, DEFAULT_ROLE_TIMEFRAMES[role])
            timeframe = self.data_service.timeframe_request(label)
            if timeframe.interval not in fetched_by_interval:
                fetched_by_interval[timeframe.interval] = self.data_service.fetch_frames(
                    tickers,
                    timeframe,
                    force_refresh=request.force_refresh,
                )
            role_frames, role_errors = fetched_by_interval[timeframe.interval]
            for ticker in tickers:
                frame = role_frames.get(ticker)
                if frame is not None:
                    frames_by_ticker[ticker][role] = frame
                else:
                    frames_by_ticker[ticker][role] = pd.DataFrame()
                    message = role_errors.get(ticker, f"No {timeframe.label} history returned")
                    errors_by_ticker[ticker].append(f"{role.title()} data: {message}")

        strategy = self.strategy or TrendBreakoutStrategy(request.config)
        results: list[SignalResult] = []
        errors: dict[str, str] = {}
        total = len(tickers)
        for position, ticker in enumerate(tickers, start=1):
            if progress:
                progress(position - 1, total, ticker)
            try:
                result = strategy.evaluate(ticker, frames_by_ticker[ticker])
            except Exception as exc:
                logger.exception("Signal calculation failed for %s", ticker)
                result = data_error_result(ticker, f"Signal calculation failed: {exc}", request.config)
            if errors_by_ticker[ticker]:
                for message in errors_by_ticker[ticker]:
                    if message not in result.warnings:
                        result.warnings.append(message)
                if result.error:
                    errors[ticker] = result.error
                else:
                    errors[ticker] = "; ".join(errors_by_ticker[ticker])
            elif result.error:
                errors[ticker] = result.error
            results.append(result)
            if progress:
                progress(position, total, ticker)
        return results, errors
