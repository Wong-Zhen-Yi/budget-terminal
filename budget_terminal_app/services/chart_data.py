from __future__ import annotations

from typing import Any

from ..cache import CacheManager
from ..data_service.results import attach_market_data_result, make_market_data_meta
from ..data_service.tasks import MarketDataTaskRunner
from ..dependencies import logger, pd, yf


CHART_CACHE_PERIOD_DAY_MAP = {
    "d": 1.0,
    "wk": 7.0,
    "mo": 30.0,
    "y": 365.0,
}


class ChartDataService:
    """Fetch chart OHLCV frames with cache freshness and stale fallback metadata."""

    def __init__(self, cache_manager: CacheManager | None = None, task_runner: MarketDataTaskRunner | None = None) -> None:
        self.cache_manager = cache_manager or CacheManager()
        self.task_runner = task_runner or MarketDataTaskRunner(default_timeout_seconds=90.0, default_retries=1)

    def required_span_days(self, period: Any) -> float | None:
        text = str(period or "").strip().lower()
        if not text or text == "max":
            return None
        for suffix, multiplier in CHART_CACHE_PERIOD_DAY_MAP.items():
            if text.endswith(suffix):
                number_text = text[:-len(suffix)].strip()
                try:
                    return float(number_text) * multiplier
                except (TypeError, ValueError):
                    return None
        return None

    def cache_covers_period(self, df: Any, period: Any) -> bool:
        if df is None or getattr(df, "empty", True):
            return False
        required_days = self.required_span_days(period)
        if required_days is None:
            return True
        try:
            index = pd.DatetimeIndex(pd.to_datetime(df.index))
        except Exception:
            return False
        if len(index) < 2:
            return False
        if getattr(index, "tz", None) is not None:
            index = index.tz_localize(None)
        coverage_days = max(0.0, (index.max() - index.min()).total_seconds() / 86400.0)
        min_acceptable_days = max(required_days - 45.0, required_days * 0.85)
        return coverage_days >= min_acceptable_days

    def frame_coverage_days(self, df: Any) -> float:
        if df is None or getattr(df, "empty", True):
            return 0.0
        try:
            index = pd.DatetimeIndex(pd.to_datetime(df.index))
        except Exception:
            return 0.0
        if len(index) < 2:
            return 0.0
        if getattr(index, "tz", None) is not None:
            index = index.tz_localize(None)
        return max(0.0, (index.max() - index.min()).total_seconds() / 86400.0)

    def normalize_datetime_index(self, values: Any) -> Any:
        index = pd.DatetimeIndex(pd.to_datetime(values))
        if getattr(index, "tz", None) is not None:
            index = index.tz_localize(None)
        return pd.DatetimeIndex(index.astype("datetime64[ns]"))

    def extract_symbol_frame(self, symbol: Any, df: Any) -> Any:
        if df is None or getattr(df, "empty", True):
            return pd.DataFrame()
        frame = df.copy()
        symbol_text = str(symbol or "").upper().strip()
        if not isinstance(frame.columns, pd.MultiIndex):
            return frame
        level0 = [str(value).upper().strip() for value in frame.columns.get_level_values(0)]
        level1 = [str(value).upper().strip() for value in frame.columns.get_level_values(1)]
        if symbol_text and symbol_text in level0:
            mask = [value == symbol_text for value in level0]
            frame = frame.loc[:, mask].copy()
            frame.columns = frame.columns.get_level_values(1)
            return frame
        if symbol_text and symbol_text in level1:
            mask = [value == symbol_text for value in level1]
            frame = frame.loc[:, mask].copy()
            frame.columns = frame.columns.get_level_values(0)
            return frame
        frame.columns = frame.columns.get_level_values(0)
        return frame

    def normalize_frame(self, symbol: Any, df: Any) -> Any:
        frame = self.extract_symbol_frame(symbol, df)
        if frame is None or getattr(frame, "empty", True):
            return pd.DataFrame()
        rename_map = {}
        for column in list(frame.columns):
            text = str(column).strip().lower()
            if text == "open":
                rename_map[column] = "Open"
            elif text == "high":
                rename_map[column] = "High"
            elif text == "low":
                rename_map[column] = "Low"
            elif text == "close":
                rename_map[column] = "Close"
            elif text == "volume":
                rename_map[column] = "Volume"
        if rename_map:
            frame = frame.rename(columns=rename_map)
        if not {"Open", "High", "Low", "Close"}.issubset(frame.columns):
            return pd.DataFrame()
        if "Volume" not in frame.columns:
            frame["Volume"] = 0.0
        frame = frame.loc[:, [column for column in ("Open", "High", "Low", "Close", "Volume") if column in frame.columns]].copy()
        frame.index = self.normalize_datetime_index(frame.index)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        return frame.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    def load_cached_frame(self, symbol: Any, *, period: Any, interval: Any, allow_stale: bool = False) -> tuple[Any, dict[str, Any]]:
        cached = self.cache_manager.get_data(
            str(symbol or "").upper().strip(),
            interval,
            allow_stale=allow_stale,
            return_metadata=True,
        )
        if not cached:
            return None, {}
        raw_frame, cache_meta = cached
        frame = self.normalize_frame(symbol, raw_frame)
        if frame is None or frame.empty:
            return None, {}
        if not allow_stale and interval in ("1d", "1wk", "1mo") and not self.cache_covers_period(frame, period):
            return None, {}
        return frame, cache_meta if isinstance(cache_meta, dict) else {}

    def fetch_base_frame_payload(self, symbol: Any, *, period: Any, interval: Any, force_refresh: bool = False) -> dict[str, Any]:
        symbol_text = str(symbol or "").upper().strip()
        if not symbol_text:
            payload = {"df": pd.DataFrame()}
            return attach_market_data_result(
                payload,
                meta=make_market_data_meta(source="input", freshness="failed", failure_reason="No chart symbol was provided."),
            )
        if not force_refresh:
            cached_frame, cache_meta = self.load_cached_frame(symbol_text, period=period, interval=interval)
            if cached_frame is not None and not cached_frame.empty:
                return attach_market_data_result(
                    {"df": cached_frame},
                    meta=make_market_data_meta(
                        source="cache",
                        freshness="fresh",
                        cache_age_seconds=cache_meta.get("cache_age_seconds"),
                    ),
                )

        stale_frame, stale_meta = self.load_cached_frame(symbol_text, period=period, interval=interval, allow_stale=True)

        def download_frame() -> Any:
            raw_df = yf.download(symbol_text, period=period, interval=interval, progress=False, auto_adjust=False)
            frame = self.normalize_frame(symbol_text, raw_df)
            if frame is None or frame.empty:
                raise ValueError(f"No chart data returned for {symbol_text}.")
            if interval in ("1d", "1wk", "1mo"):
                self.cache_manager.save_data(symbol_text, interval, frame)
            return frame

        result = self.task_runner.run(
            f"chart_fetch:{symbol_text}:{period}:{interval}",
            download_frame,
            source="yfinance",
            cache_fallback=(lambda: stale_frame) if stale_frame is not None and not stale_frame.empty else None,
            cache_age_seconds=stale_meta.get("cache_age_seconds") if isinstance(stale_meta, dict) else None,
            success_check=lambda frame: frame is not None and not getattr(frame, "empty", True),
            failure_reason=f"No chart data returned for {symbol_text}.",
        )
        frame = result.data if result.data is not None and not isinstance(result.data, dict) else pd.DataFrame()
        return attach_market_data_result({"df": frame}, meta=result.meta, errors=result.errors)

    def fetch_compare_frames_batch_payload(self, symbols: Any, *, period: Any, interval: Any) -> dict[str, Any]:
        batch_symbols = [str(symbol or "").upper().strip() for symbol in list(symbols or []) if str(symbol or "").upper().strip()]
        if not batch_symbols:
            return attach_market_data_result(
                {"frames": {}, "missing": []},
                meta=make_market_data_meta(source="input", freshness="failed", failure_reason="No compare symbols were provided."),
            )

        def download_batch() -> dict[str, Any]:
            raw_batch = yf.download(
                batch_symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                progress=False,
                auto_adjust=False,
                threads=True,
            )
            frame_map = {}
            missing = []
            for symbol in batch_symbols:
                frame = self.normalize_frame(symbol, raw_batch)
                if frame is None or frame.empty:
                    missing.append(symbol)
                    continue
                frame_map[symbol] = frame
                if interval in ("1d", "1wk", "1mo"):
                    self.cache_manager.save_data(symbol, interval, frame)
            if not frame_map:
                raise ValueError("No compare chart data returned.")
            return {"frames": frame_map, "missing": missing}

        result = self.task_runner.run(
            f"compare_batch:{period}:{interval}",
            download_batch,
            source="yfinance",
            partial=False,
            success_check=lambda payload: isinstance(payload, dict) and bool(payload.get("frames")),
            failure_reason="No compare chart data returned.",
        )
        payload = result.data if isinstance(result.data, dict) and "frames" in result.data else {"frames": {}, "missing": batch_symbols}
        if payload.get("missing"):
            result.meta["freshness"] = "partial"
            result.meta["is_partial"] = True
            result.meta["failure_reason"] = f"{len(payload.get('missing', []))} compare ticker(s) returned no data."
        return attach_market_data_result(payload, meta=result.meta, errors=result.errors)

    def fetch_daily_ma200_payload(self, symbol: Any, source_df: Any) -> dict[str, Any]:
        symbol_text = str(symbol or "").upper().strip()
        source = "cache"
        raw_daily_df = self.cache_manager.get_data(symbol_text, "1d", allow_stale=True)
        daily_df = self.normalize_frame(symbol_text, raw_daily_df)
        if daily_df is None or daily_df.empty or self.frame_coverage_days(daily_df) < 260.0:
            source = "yfinance"
            try:
                raw_daily_df = yf.download(symbol_text, period="5y", interval="1d", progress=False, auto_adjust=False)
                daily_df = self.normalize_frame(symbol_text, raw_daily_df)
                if daily_df is not None and not daily_df.empty:
                    self.cache_manager.save_data(symbol_text, "1d", daily_df)
            except Exception as exc:
                logger.info("Daily MA200 fetch failed for %s: %s", symbol_text, exc)
                daily_df = None
        empty = pd.Series(index=source_df.index, dtype=float)
        if daily_df is None or getattr(daily_df, "empty", True):
            return attach_market_data_result(
                {"series": empty},
                meta=make_market_data_meta(source=source, freshness="partial", failure_reason="200-day moving average data unavailable."),
            )
        frame = self.normalize_frame(symbol_text, daily_df)
        if frame is None or frame.empty or "Close" not in frame.columns:
            return attach_market_data_result({"series": empty}, meta=make_market_data_meta(source=source, freshness="partial"))
        daily_ma = pd.Series(frame["Close"]).astype(float).rolling(200, min_periods=200).mean().dropna()
        if daily_ma.empty:
            return attach_market_data_result({"series": empty}, meta=make_market_data_meta(source=source, freshness="partial"))
        source_index = self.normalize_datetime_index(source_df.index)
        daily_index = self.normalize_datetime_index(daily_ma.index)
        source_frame = pd.DataFrame(index=source_index).sort_index()
        daily_frame = pd.DataFrame({"ma200": list(daily_ma.values)}, index=daily_index).sort_index()
        aligned = pd.merge_asof(source_frame, daily_frame, left_index=True, right_index=True, direction="backward")["ma200"]
        aligned.index = source_df.index
        return attach_market_data_result({"series": aligned}, meta=make_market_data_meta(source=source, freshness="fresh"))
