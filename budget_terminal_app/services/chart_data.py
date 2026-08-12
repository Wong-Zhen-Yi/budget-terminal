from __future__ import annotations

from typing import Any

from ..cache import CacheManager
from ..data_service.results import (
    attach_market_data_result,
    make_market_data_error,
    make_market_data_meta,
)
from ..data_service.tasks import MarketDataTaskRunner
from ..dependencies import logger, pd, yf


CHART_CACHE_PERIOD_DAY_MAP = {
    "d": 1.0,
    "wk": 7.0,
    "mo": 30.0,
    "y": 365.0,
}

_CHART_PRICE_FIELD_NAMES = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "adj close": "Adj Close",
    "volume": "Volume",
}


class ChartDataService:
    """Fetch chart OHLCV frames with cache freshness and stale fallback metadata."""

    def __init__(self, cache_manager: CacheManager | None = None, task_runner: MarketDataTaskRunner | None = None) -> None:
        self.cache_manager = cache_manager or CacheManager()
        self._owns_task_runner = task_runner is None
        self.task_runner = task_runner or MarketDataTaskRunner(default_timeout_seconds=90.0, default_retries=1)

    def close(self) -> None:
        if self._owns_task_runner:
            self.task_runner.shutdown(wait=False)

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
        field_scores = []
        for level in range(frame.columns.nlevels):
            values = [str(value).strip().casefold() for value in frame.columns.get_level_values(level)]
            recognized = [value for value in values if value in _CHART_PRICE_FIELD_NAMES]
            field_scores.append((len(set(recognized)), len(recognized)))
        field_level = max(range(len(field_scores)), key=field_scores.__getitem__)
        if field_scores[field_level][0] <= 0:
            logger.warning("Chart data for %s has no recognizable OHLCV MultiIndex level: %s", symbol_text, list(frame.columns))
            return pd.DataFrame()

        symbol_level = None
        for level in range(frame.columns.nlevels):
            if level == field_level:
                continue
            values = [str(value).upper().strip() for value in frame.columns.get_level_values(level)]
            if symbol_text and symbol_text in values:
                symbol_level = level
                break
        if symbol_level is not None:
            values = [str(value).upper().strip() for value in frame.columns.get_level_values(symbol_level)]
            frame = frame.loc[:, [value == symbol_text for value in values]].copy()
        elif any(
            len({str(value).upper().strip() for value in frame.columns.get_level_values(level)}) > 1
            for level in range(frame.columns.nlevels)
            if level != field_level
        ):
            logger.warning("Chart data for %s contains multiple symbols but no exact symbol match.", symbol_text)
            return pd.DataFrame()
        frame.columns = frame.columns.get_level_values(field_level)
        return frame

    def _coalesce_price_column(self, frame: Any, canonical_name: str) -> Any:
        matches = [
            index
            for index, column in enumerate(frame.columns)
            if str(column).strip().casefold() == canonical_name.casefold()
        ]
        if not matches:
            return None
        series = pd.to_numeric(frame.iloc[:, matches[0]], errors="coerce")
        for index in matches[1:]:
            candidate = pd.to_numeric(frame.iloc[:, index], errors="coerce")
            overlap = series.notna() & candidate.notna()
            if bool(overlap.any()) and not series.loc[overlap].equals(candidate.loc[overlap]):
                logger.warning("Chart data contains conflicting duplicate %s columns; preserving the first usable value.", canonical_name)
            series = series.combine_first(candidate)
        return series

    def normalize_frame(self, symbol: Any, df: Any) -> Any:
        frame = self.extract_symbol_frame(symbol, df)
        if frame is None or getattr(frame, "empty", True):
            return pd.DataFrame()
        normalized_columns = {}
        for source_name, canonical_name in _CHART_PRICE_FIELD_NAMES.items():
            series = self._coalesce_price_column(frame, source_name)
            if series is not None:
                normalized_columns[canonical_name] = series
        if not {"Open", "High", "Low", "Close"}.issubset(normalized_columns):
            return pd.DataFrame()
        if "Volume" not in normalized_columns:
            normalized_columns["Volume"] = pd.Series(0.0, index=frame.index, dtype=float)
        frame = pd.DataFrame(
            {column: normalized_columns[column] for column in ("Open", "High", "Low", "Close", "Volume")},
            index=frame.index,
        )
        frame.index = self.normalize_datetime_index(frame.index)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        return frame.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    def aggregate_hourly_to_four_hour_frame(self, df: Any) -> Any:
        """Build synthetic 4-hour OHLCV candles from consecutive same-session hourly rows."""
        if df is None or getattr(df, "empty", True):
            return pd.DataFrame()
        frame = df.copy()
        frame.index = self.normalize_datetime_index(frame.index)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(frame.columns):
            return pd.DataFrame()
        records: list[dict[str, Any]] = []
        timestamps = []
        for _, day_frame in frame.groupby(frame.index.date, sort=True):
            day_frame = day_frame.sort_index()
            for start in range(0, len(day_frame), 4):
                chunk = day_frame.iloc[start:start + 4]
                if chunk.empty:
                    continue
                timestamps.append(chunk.index[-1])
                records.append(
                    {
                        "Open": float(chunk["Open"].iloc[0]),
                        "High": float(chunk["High"].max()),
                        "Low": float(chunk["Low"].min()),
                        "Close": float(chunk["Close"].iloc[-1]),
                        "Volume": float(chunk["Volume"].fillna(0.0).sum()),
                    }
                )
        if not records:
            return pd.DataFrame()
        aggregated = pd.DataFrame(records, index=pd.DatetimeIndex(timestamps))
        aggregated.index = self.normalize_datetime_index(aggregated.index)
        return aggregated.dropna(subset=["Open", "High", "Low", "Close"]).copy()

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

    def fetch_base_frame_payload(
        self,
        symbol: Any,
        *,
        period: Any,
        interval: Any,
        force_refresh: bool = False,
        include_extended_hours: bool = False,
    ) -> dict[str, Any]:
        symbol_text = str(symbol or "").upper().strip()
        if not symbol_text:
            payload = {"df": pd.DataFrame()}
            return attach_market_data_result(
                payload,
                meta=make_market_data_meta(source="input", freshness="failed", failure_reason="No chart symbol was provided."),
            )
        if not force_refresh and not include_extended_hours:
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

        stale_frame, stale_meta = (None, {})
        if not include_extended_hours:
            stale_frame, stale_meta = self.load_cached_frame(symbol_text, period=period, interval=interval, allow_stale=True)

        def download_frame() -> Any:
            fetch_interval = "1h" if str(interval or "").strip().lower() == "4h" else interval
            raw_df = yf.download(
                symbol_text,
                period=period,
                interval=fetch_interval,
                progress=False,
                auto_adjust=False,
                prepost=bool(include_extended_hours),
            )
            frame = self.normalize_frame(symbol_text, raw_df)
            if str(interval or "").strip().lower() == "4h":
                frame = self.aggregate_hourly_to_four_hour_frame(frame)
            if frame is None or frame.empty:
                raise ValueError(f"No chart data returned for {symbol_text}.")
            if not include_extended_hours and interval in ("1d", "1wk", "1mo"):
                self.cache_manager.save_data(symbol_text, interval, frame)
            return frame

        result = self.task_runner.run(
            f"chart_fetch:{symbol_text}:{period}:{interval}:extended={int(bool(include_extended_hours))}",
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

    def fetch_relationship_frames_payload(
        self,
        symbols: Any,
        *,
        period: Any,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Fetch two adjusted daily history frames without touching ordinary chart caches."""
        normalized = []
        for value in list(symbols or []):
            symbol = str(value or "").upper().strip()
            if symbol:
                normalized.append(symbol)
        if len(normalized) != 2 or normalized[0] == normalized[1]:
            reason = "Enter two different ticker symbols."
            return attach_market_data_result(
                {"frames": {}, "missing": normalized},
                meta=make_market_data_meta(source="input", freshness="failed", failure_reason=reason),
                errors=make_market_data_error(source="input", reason=reason, operation="relationship_history"),
            )

        period_text = str(period or "1y").strip().lower()
        if period_text not in {"1mo", "3mo", "6mo", "1y", "5y", "max"}:
            period_text = "1y"
        cache_interval = "1d_adj"
        frames: dict[str, Any] = {}
        fresh_cache_ages = []
        stale_frames: dict[str, Any] = {}
        stale_cache_ages = []

        for symbol in normalized:
            if not force_refresh and period_text != "max":
                cached = self.cache_manager.get_data(
                    symbol,
                    cache_interval,
                    return_metadata=True,
                )
                if cached:
                    cached_frame = self.normalize_frame(symbol, cached[0])
                    cached_meta = cached[1] if isinstance(cached[1], dict) else {}
                    if cached_frame is not None and not cached_frame.empty and self.cache_covers_period(cached_frame, period_text):
                        frames[symbol] = cached_frame
                        fresh_cache_ages.append(cached_meta.get("cache_age_seconds"))
            stale = self.cache_manager.get_data(
                symbol,
                cache_interval,
                allow_stale=True,
                return_metadata=True,
            )
            if stale:
                stale_frame = self.normalize_frame(symbol, stale[0])
                stale_meta = stale[1] if isinstance(stale[1], dict) else {}
                if stale_frame is not None and not stale_frame.empty:
                    stale_frames[symbol] = stale_frame
                    stale_cache_ages.append(stale_meta.get("cache_age_seconds"))

        pending = [symbol for symbol in normalized if symbol not in frames]
        errors = []
        used_live = False
        used_stale = False
        missing_from_live: list[str] = []
        if pending:
            def download_adjusted() -> dict[str, Any]:
                raw = yf.download(
                    pending,
                    period=period_text,
                    interval="1d",
                    group_by="ticker",
                    progress=False,
                    auto_adjust=True,
                    threads=True,
                )
                downloaded = {}
                unavailable = []
                for symbol in pending:
                    frame = self.normalize_frame(symbol, raw)
                    if frame is None or frame.empty:
                        unavailable.append(symbol)
                        continue
                    downloaded[symbol] = frame
                    self.cache_manager.save_data(symbol, cache_interval, frame)
                if not downloaded:
                    raise ValueError("No adjusted relationship history was returned.")
                return {"frames": downloaded, "missing": unavailable}

            fallback_payload = {
                "frames": {symbol: stale_frames[symbol] for symbol in pending if symbol in stale_frames},
                "missing": [symbol for symbol in pending if symbol not in stale_frames],
            }
            result = self.task_runner.run(
                f"relationship_history:{','.join(pending)}:{period_text}",
                download_adjusted,
                source="yfinance adjusted history",
                cache_fallback=(lambda: fallback_payload) if fallback_payload["frames"] else None,
                cache_source="adjusted history cache",
                cache_age_seconds=max(
                    (float(value) for value in stale_cache_ages if value is not None),
                    default=None,
                ),
                success_check=lambda payload: isinstance(payload, dict) and bool(payload.get("frames")),
                failure_reason="Adjusted relationship history could not be loaded.",
            )
            errors.extend(result.errors)
            downloaded_payload = result.data if isinstance(result.data, dict) else {"frames": {}, "missing": pending}
            downloaded_frames = downloaded_payload.get("frames", {}) if isinstance(downloaded_payload.get("frames"), dict) else {}
            frames.update(downloaded_frames)
            missing_from_live = list(downloaded_payload.get("missing", []))
            used_stale = str(result.meta.get("freshness")) == "stale"
            used_live = bool(downloaded_frames) and not used_stale

            if used_live and missing_from_live:
                for symbol in list(missing_from_live):
                    stale_frame = stale_frames.get(symbol)
                    if stale_frame is None or stale_frame.empty:
                        continue
                    frames[symbol] = stale_frame
                    missing_from_live.remove(symbol)
                    used_stale = True

        missing = [symbol for symbol in normalized if symbol not in frames]
        source_parts = []
        if fresh_cache_ages:
            source_parts.append("adjusted history cache")
        if used_live:
            source_parts.append("yfinance adjusted history")
        if used_stale:
            source_parts.append("stale adjusted history cache")
        source = ", ".join(source_parts) or "adjusted history cache"

        if not frames:
            freshness = "failed"
            reason = "Adjusted relationship history could not be loaded."
        elif missing:
            freshness = "partial"
            reason = f"No adjusted history was available for {', '.join(missing)}."
        elif used_stale:
            freshness = "stale"
            reason = "Showing cached adjusted history because part of the live refresh failed."
        else:
            freshness = "fresh"
            reason = ""

        cache_ages = [*fresh_cache_ages]
        if used_stale:
            cache_ages.extend(stale_cache_ages)
        return attach_market_data_result(
            {"frames": frames, "missing": missing},
            meta=make_market_data_meta(
                source=source,
                freshness=freshness,
                failure_reason=reason,
                cache_age_seconds=max(
                    (float(value) for value in cache_ages if value is not None),
                    default=None,
                ),
            ),
            errors=errors,
        )

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
