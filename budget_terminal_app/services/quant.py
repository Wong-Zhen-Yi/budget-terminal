"""Quantitative screening and pairs (stat-arb) analytics.

Deliberately Qt-free and presentation-independent so the smoke tests can exercise every
calculation without a ``QApplication``.

The pinned runtime dependencies are pandas / yfinance / PySide6 / pyqtgraph — there is no numpy,
scipy or statsmodels available. Every statistic here is therefore closed-form single-regressor
OLS built on pandas and ``math``, in the same style as
``services/relationship_analysis._regression_statistics``. In particular the stationarity check is
a plain Dickey-Fuller t-statistic compared against tabulated critical values; without scipy there
is no distribution to integrate, so no p-value is claimed anywhere.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Sequence

from ..cache import CacheManager
from ..dependencies import YF_LOCK, logger, math, pd, yf
from .automatic_signal_scanner import (
    AutomaticTickerUniverseService,
    AutoTickerCandidate,
    AutoUniverseConfig,
)
from .relationship_analysis import build_relationship_analysis
from .signal_scanner import ScanCancelled, SignalMarketDataService, normalize_tickers
from .technical_analysis import calculate_rsi

_TRADING_DAYS = 252.0

#: Momentum lookbacks in completed trading sessions, roughly 1 / 3 / 6 / 12 months.
_MOMENTUM_WINDOWS = (
    ("momentum_1m", 21),
    ("momentum_3m", 63),
    ("momentum_6m", 126),
    ("momentum_12m", 252),
)

#: Composite weights: momentum dominates, risk-adjusted return next, low volatility as a tilt.
_COMPOSITE_WEIGHTS = (("momentum", 0.5), ("sharpe", 0.3), ("low_volatility", 0.2))

#: Dickey-Fuller critical values for the constant-without-trend case at large sample sizes
#: (MacKinnon). Tabulated because computing them needs a distribution scipy would provide.
DICKEY_FULLER_CRITICAL_VALUES = {"1%": -3.43, "5%": -2.86, "10%": -2.57}

MIN_PAIR_OBSERVATIONS = 60


@dataclass(frozen=True)
class QuantConfig:
    """Tunables for the Quant screener and pairs lab."""

    history_period: str = "2y"
    rsi_period: int = 14
    sma_window: int = 50
    dollar_volume_lookback: int = 20
    download_chunk: int = 50
    min_observations: int = MIN_PAIR_OBSERVATIONS
    #: Tickers carried into pair discovery. 40 names is 780 candidate pairs, which the vectorized
    #: correlation prescreen handles in one call.
    pair_universe_limit: int = 40
    #: Pairs kept from the correlation prescreen for the (much costlier) cointegration pass.
    pair_prescreen_limit: int = 150
    pair_result_limit: int = 40
    spread_z_window: int = 60
    result_cache_seconds: int = 12 * 60 * 60


@dataclass(frozen=True)
class QuantScreenRow:
    """One ranked ticker in the screener table."""

    ticker: str
    name: str = ""
    exchange: str = ""
    last_price: float | None = None
    market_cap: float | None = None
    median_dollar_volume: float | None = None
    momentum_1m: float | None = None
    momentum_3m: float | None = None
    momentum_6m: float | None = None
    momentum_12m: float | None = None
    volatility_pct: float | None = None
    sharpe: float | None = None
    max_drawdown_pct: float | None = None
    z_score: float | None = None
    rsi: float | None = None
    composite: float | None = None
    rank: int = 0
    observations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> QuantScreenRow:
        fields = set(cls.__dataclass_fields__)
        return cls(**{key: value[key] for key in fields if key in value})


@dataclass(frozen=True)
class QuantPairRow:
    """One candidate pair scored for mean reversion."""

    left: str
    right: str
    correlation: float | None = None
    hedge_ratio: float | None = None
    spread_z: float | None = None
    half_life: float | None = None
    hurst: float | None = None
    dickey_fuller: float | None = None
    stationary_at: str = ""
    score: float | None = None
    rank: int = 0
    observations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> QuantPairRow:
        fields = set(cls.__dataclass_fields__)
        return cls(**{key: value[key] for key in fields if key in value})


@dataclass
class QuantScanPayload:
    """Everything one Quant scan produces, shared by both sub-tabs."""

    rows: list[QuantScreenRow] = field(default_factory=list)
    pairs: list[QuantPairRow] = field(default_factory=list)
    source: str = "Yahoo Finance"
    sourced_at: dt.datetime = field(default_factory=dt.datetime.now)
    started_at: dt.datetime = field(default_factory=dt.datetime.now)
    completed_at: dt.datetime = field(default_factory=dt.datetime.now)
    universe_size: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    universe_from_cache: bool = False


# --------------------------------------------------------------------------- series helpers


def _finite_series(values: Any) -> Any:
    """Return a float series with NaN/inf dropped and duplicate timestamps collapsed."""

    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if series.empty:
        return pd.Series(dtype=float)
    finite = series.map(lambda value: math.isfinite(float(value)))
    series = series[finite].astype(float)
    if not isinstance(series.index, pd.DatetimeIndex):
        return series
    return series[~series.index.duplicated(keep="last")].sort_index()


def _close_volume(frame: Any) -> tuple[Any, Any]:
    """Split an OHLCV frame into a positive close series and its aligned volume series."""

    empty = pd.Series(dtype=float)
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame.columns:
        return empty, empty
    selected = frame["Close"]
    if isinstance(selected, pd.DataFrame):
        if selected.shape[1] != 1:
            return empty, empty
        selected = selected.iloc[:, 0]
    close = pd.Series(selected)
    index = pd.DatetimeIndex(pd.to_datetime(close.index, errors="coerce"))
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    close.index = index.normalize()
    close = _finite_series(close)
    close = close[close > 0.0]
    if close.empty:
        return empty, empty
    volume = empty
    if "Volume" in frame.columns:
        raw_volume = frame["Volume"]
        if isinstance(raw_volume, pd.DataFrame):
            raw_volume = raw_volume.iloc[:, 0] if raw_volume.shape[1] == 1 else None
        if raw_volume is not None:
            candidate = pd.Series(raw_volume)
            candidate.index = index.normalize()
            volume = _finite_series(candidate).reindex(close.index).dropna()
    return close, volume


def _optional_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


# --------------------------------------------------------------------------- regression core


def ordinary_least_squares(y_values: Any, x_values: Any) -> dict[str, Any] | None:
    """Fit ``y = alpha + beta * x`` in closed form.

    Returns ``None`` when the fit is undefined (too few points, or a constant regressor). The
    ``t_statistic`` is the ratio of ``beta`` to its standard error, which is what the
    Dickey-Fuller check consumes.
    """

    frame = pd.concat(
        [pd.Series(y_values).rename("y"), pd.Series(x_values).rename("x")],
        axis=1,
        join="inner",
    ).dropna()
    observations = int(len(frame))
    if observations < 3:
        return None
    y_series = frame["y"].astype(float)
    x_series = frame["x"].astype(float)
    x_mean = float(x_series.mean())
    y_mean = float(y_series.mean())
    centered_x = x_series - x_mean
    denominator = float((centered_x * centered_x).sum())
    if not math.isfinite(denominator) or denominator <= 0.0:
        return None
    beta = float((centered_x * (y_series - y_mean)).sum() / denominator)
    alpha = float(y_mean - beta * x_mean)
    if not (math.isfinite(beta) and math.isfinite(alpha)):
        return None
    residuals = y_series - (alpha + beta * x_series)
    residual_sum_squares = float((residuals * residuals).sum())
    standard_error = None
    t_statistic = None
    if observations > 2 and residual_sum_squares > 0.0:
        variance = residual_sum_squares / (observations - 2)
        candidate = math.sqrt(variance / denominator)
        if math.isfinite(candidate) and candidate > 0.0:
            standard_error = candidate
            t_statistic = beta / candidate
    return {
        "beta": beta,
        "alpha": alpha,
        "residuals": residuals,
        "observations": observations,
        "std_error": standard_error,
        "t_statistic": t_statistic,
    }


def hurst_exponent(values: Any, *, max_lag: int = 20) -> float | None:
    """Estimate the Hurst exponent from the log-log slope of increment dispersion.

    For a series whose increments scale as ``lag ** H``, regressing ``log(std(diff(lag)))`` on
    ``log(lag)`` recovers ``H`` directly. Below 0.5 indicates mean reversion, 0.5 a random walk.
    """

    series = _finite_series(values)
    if len(series) < max_lag * 3:
        return None
    log_lags: list[float] = []
    log_dispersion: list[float] = []
    for lag in range(2, int(max_lag) + 1):
        differences = series.diff(lag).dropna()
        if len(differences) < 8:
            continue
        dispersion = float(differences.std(ddof=1))
        if not math.isfinite(dispersion) or dispersion <= 0.0:
            continue
        log_lags.append(math.log(float(lag)))
        log_dispersion.append(math.log(dispersion))
    if len(log_lags) < 4:
        return None
    fit = ordinary_least_squares(pd.Series(log_dispersion), pd.Series(log_lags))
    return _optional_float(fit["beta"]) if fit else None


def mean_reversion_stats(spread: Any) -> dict[str, Any]:
    """Fit the AR(1) model ``delta = lambda * spread[t-1] + c`` on a spread series.

    A negative ``lambda`` means the spread pulls back toward its mean, and the half-life follows
    as ``-ln(2) / lambda``. The regression t-statistic is the Dickey-Fuller statistic for the
    constant-without-trend case with no augmentation lags.
    """

    empty = {
        "half_life": None,
        "dickey_fuller": None,
        "stationary_at": "",
        "observations": 0,
        "decay": None,
    }
    series = _finite_series(spread)
    observations = int(len(series))
    if observations < MIN_PAIR_OBSERVATIONS:
        return {**empty, "observations": observations}
    fit = ordinary_least_squares(series.diff(), series.shift(1))
    if fit is None:
        return {**empty, "observations": observations}
    decay = float(fit["beta"])
    half_life = None
    if decay < 0.0:
        candidate = -math.log(2.0) / decay
        if math.isfinite(candidate) and candidate > 0.0:
            half_life = candidate
    statistic = _optional_float(fit["t_statistic"])
    stationary_at = ""
    if statistic is not None:
        for label in ("1%", "5%", "10%"):
            if statistic <= DICKEY_FULLER_CRITICAL_VALUES[label]:
                stationary_at = label
                break
    return {
        "half_life": half_life,
        "dickey_fuller": statistic,
        "stationary_at": stationary_at,
        "observations": int(fit["observations"]),
        "decay": decay,
    }


def build_pair_spread(left_close: Any, right_close: Any, *, z_window: int = 60) -> dict[str, Any]:
    """Regress two price levels onto each other and describe the residual spread.

    The hedge ratio is the OLS beta on **price levels**, a different quantity from the
    return-space beta in ``services/relationship_analysis``; using the latter here would size the
    short leg wrongly.
    """

    aligned = pd.concat(
        [_finite_series(left_close).rename("left"), _finite_series(right_close).rename("right")],
        axis=1,
        join="inner",
    ).dropna()
    aligned = aligned[(aligned["left"] > 0.0) & (aligned["right"] > 0.0)].sort_index()
    empty = {
        "spread": pd.Series(dtype=float),
        "spread_z": pd.Series(dtype=float),
        "hedge_ratio": None,
        "intercept": None,
        "latest_z": None,
        "correlation": None,
        "observations": int(len(aligned)),
    }
    if len(aligned) < MIN_PAIR_OBSERVATIONS:
        return empty
    fit = ordinary_least_squares(aligned["left"], aligned["right"])
    if fit is None:
        return empty
    spread = pd.Series(fit["residuals"], index=aligned.index).astype(float)
    window = max(int(z_window), 2)
    rolling_mean = spread.rolling(window=window, min_periods=window).mean()
    rolling_std = spread.rolling(window=window, min_periods=window).std(ddof=1)
    spread_z = ((spread - rolling_mean) / rolling_std.replace(0.0, float("nan"))).replace(
        [float("inf"), float("-inf")], float("nan")
    )
    valid_z = spread_z.dropna()
    returns = aligned.pct_change(fill_method=None).dropna()
    correlation = None
    if len(returns) >= 5:
        correlation = _optional_float(returns["left"].corr(returns["right"]))
    return {
        "spread": spread,
        "spread_z": spread_z,
        "hedge_ratio": _optional_float(fit["beta"]),
        "intercept": _optional_float(fit["alpha"]),
        "latest_z": float(valid_z.iloc[-1]) if not valid_z.empty else None,
        "correlation": correlation,
        "observations": int(len(aligned)),
    }


def score_pair(stats: Mapping[str, Any]) -> float | None:
    """Blend correlation, mean-reversion speed and stationarity into one 0-100 score.

    Correlation gives the pair a reason to track together; the half-life term rewards spreads that
    revert within a tradable horizon rather than over years; the Dickey-Fuller and Hurst terms
    reward spreads that actually look stationary.
    """

    correlation = _optional_float(stats.get("correlation"))
    half_life = _optional_float(stats.get("half_life"))
    statistic = _optional_float(stats.get("dickey_fuller"))
    hurst = _optional_float(stats.get("hurst"))
    if correlation is None or half_life is None:
        return None
    score = 40.0 * min(abs(correlation), 1.0)
    # Peak credit around a ten-session half-life, tapering off logarithmically either side.
    if 1.0 <= half_life <= 120.0:
        score += 25.0 * math.exp(-abs(math.log(half_life / 10.0)))
    if statistic is not None:
        score += 25.0 * max(0.0, min(1.0, (-statistic - 1.5) / 2.0))
    if hurst is not None:
        score += 10.0 * max(0.0, min(1.0, (0.5 - hurst) / 0.3))
    return round(score, 2)


# --------------------------------------------------------------------------- screener metrics


def screen_metrics(frame: Any, *, config: QuantConfig | None = None) -> dict[str, Any]:
    """Compute the per-ticker factor set from one daily OHLCV frame."""

    settings = config or QuantConfig()
    close, volume = _close_volume(frame)
    metrics: dict[str, Any] = {key: None for key, _ in _MOMENTUM_WINDOWS}
    metrics.update(
        {
            "observations": int(len(close)),
            "last_price": None,
            "volatility_pct": None,
            "sharpe": None,
            "max_drawdown_pct": None,
            "z_score": None,
            "rsi": None,
            "median_dollar_volume": None,
        }
    )
    if close.empty:
        return metrics
    latest = float(close.iloc[-1])
    metrics["last_price"] = latest
    for key, window in _MOMENTUM_WINDOWS:
        if len(close) > window:
            previous = float(close.iloc[-(window + 1)])
            if previous > 0.0:
                metrics[key] = (latest / previous - 1.0) * 100.0
    returns = close.pct_change(fill_method=None).dropna()
    if len(returns) >= 20:
        deviation = float(returns.std(ddof=1))
        if math.isfinite(deviation) and deviation > 0.0:
            metrics["volatility_pct"] = deviation * math.sqrt(_TRADING_DAYS) * 100.0
            # No risk-free rate, matching the convention already used by PortfolioAnalyticsWorker.
            metrics["sharpe"] = float(returns.mean()) / deviation * math.sqrt(_TRADING_DAYS)
    drawdown = close / close.cummax() - 1.0
    metrics["max_drawdown_pct"] = _optional_float(float(drawdown.min()) * 100.0)
    if len(close) >= settings.sma_window:
        recent = close.iloc[-settings.sma_window :]
        deviation = float(recent.std(ddof=1))
        if math.isfinite(deviation) and deviation > 0.0:
            metrics["z_score"] = (latest - float(recent.mean())) / deviation
    if len(close) > settings.rsi_period:
        rsi_series = _finite_series(calculate_rsi(close, period=settings.rsi_period))
        if not rsi_series.empty:
            metrics["rsi"] = float(rsi_series.iloc[-1])
    if not volume.empty:
        dollar_volume = (close * volume).replace([float("inf"), float("-inf")], float("nan")).dropna()
        dollar_volume = dollar_volume[dollar_volume > 0.0].iloc[-settings.dollar_volume_lookback :]
        if not dollar_volume.empty:
            metrics["median_dollar_volume"] = float(dollar_volume.median())
    return metrics


def _percentile_ranks(values: Sequence[float | None]) -> list[float | None]:
    series = pd.Series(
        [value if value is not None else float("nan") for value in values],
        dtype=float,
    )
    if series.dropna().empty:
        return [None] * len(series)
    ranks = series.rank(pct=True) * 100.0
    return [None if pd.isna(value) else float(value) for value in ranks]


def rank_screen_rows(rows: Sequence[QuantScreenRow]) -> list[QuantScreenRow]:
    """Assign each row a cross-sectional composite percentile and a rank.

    Ranking is relative to the sourced universe, so a composite only means anything alongside the
    rest of the table it was computed with.
    """

    if not rows:
        return []
    momentum_ranks = [
        _percentile_ranks([getattr(row, key) for row in rows])
        for key in ("momentum_3m", "momentum_6m", "momentum_12m")
    ]
    sharpe_ranks = _percentile_ranks([row.sharpe for row in rows])
    volatility_ranks = _percentile_ranks(
        [None if row.volatility_pct is None else -row.volatility_pct for row in rows]
    )
    scored: list[QuantScreenRow] = []
    for position, row in enumerate(rows):
        available = [ranks[position] for ranks in momentum_ranks if ranks[position] is not None]
        components = {
            "momentum": sum(available) / len(available) if available else None,
            "sharpe": sharpe_ranks[position],
            "low_volatility": volatility_ranks[position],
        }
        weighted = [
            (components[key] * weight, weight)
            for key, weight in _COMPOSITE_WEIGHTS
            if components[key] is not None
        ]
        composite = None
        if weighted:
            total_weight = sum(weight for _, weight in weighted)
            composite = round(sum(value for value, _ in weighted) / total_weight, 2)
        scored.append(QuantScreenRow(**{**asdict(row), "composite": composite}))
    scored.sort(key=lambda item: (-(item.composite if item.composite is not None else -1.0), item.ticker))
    return [
        QuantScreenRow(**{**asdict(row), "rank": position})
        for position, row in enumerate(scored, start=1)
    ]


def discover_pairs(
    closes_by_ticker: Mapping[str, Any],
    *,
    config: QuantConfig | None = None,
) -> list[QuantPairRow]:
    """Rank mean-reverting pairs out of a ticker universe.

    A full cointegration fit on every combination is wasteful — 40 tickers is already 780 pairs.
    The correlation matrix is a single vectorized call, so it prescreens down to the most related
    pairs and only those get the costly per-pair regression work.
    """

    settings = config or QuantConfig()
    columns = {}
    for ticker, series in closes_by_ticker.items():
        cleaned = _finite_series(series)
        if len(cleaned) >= settings.min_observations:
            columns[str(ticker)] = cleaned
    if len(columns) < 2:
        return []
    frame = pd.DataFrame(columns).dropna()
    if frame.shape[1] < 2 or len(frame) < settings.min_observations:
        return []
    returns = frame.pct_change(fill_method=None).dropna()
    if len(returns) < settings.min_observations // 2:
        return []
    correlations = returns.corr()
    tickers = list(frame.columns)
    prescreened: list[tuple[float, str, str]] = []
    for left_index, left in enumerate(tickers):
        for right in tickers[left_index + 1 :]:
            correlation = _optional_float(correlations.at[left, right])
            if correlation is None:
                continue
            prescreened.append((abs(correlation), left, right))
    prescreened.sort(key=lambda item: (-item[0], item[1], item[2]))
    candidates: list[QuantPairRow] = []
    for _, left, right in prescreened[: max(1, settings.pair_prescreen_limit)]:
        spread_info = build_pair_spread(frame[left], frame[right], z_window=settings.spread_z_window)
        spread = spread_info["spread"]
        if spread.empty:
            continue
        reversion = mean_reversion_stats(spread)
        stats = {
            "correlation": spread_info["correlation"],
            "half_life": reversion["half_life"],
            "dickey_fuller": reversion["dickey_fuller"],
            "hurst": hurst_exponent(spread),
        }
        score = score_pair(stats)
        if score is None:
            continue
        candidates.append(
            QuantPairRow(
                left=left,
                right=right,
                correlation=spread_info["correlation"],
                hedge_ratio=spread_info["hedge_ratio"],
                spread_z=spread_info["latest_z"],
                half_life=stats["half_life"],
                hurst=stats["hurst"],
                dickey_fuller=stats["dickey_fuller"],
                stationary_at=reversion["stationary_at"],
                score=score,
                observations=spread_info["observations"],
            )
        )
    candidates.sort(key=lambda item: (-(item.score or 0.0), item.left, item.right))
    return [
        QuantPairRow(**{**asdict(row), "rank": position})
        for position, row in enumerate(candidates[: max(1, settings.pair_result_limit)], start=1)
    ]


# --------------------------------------------------------------------------- services


class QuantUniverseService(AutomaticTickerUniverseService):
    """Source a wider liquid US-equity universe than the Signals scanner uses.

    The base class keys its cache with class attributes. Overriding them keeps this deliberately
    larger universe from overwriting the Signals page's cached shortlist.
    """

    _CACHE_NAMESPACE = "quant_universe"
    _CACHE_KEY = "liquid_us_v1"


class QuantAnalyticsService:
    """Run universe sourcing, factor scoring and pair discovery as one scan."""

    _RESULT_NAMESPACE = "quant_results"
    _RESULT_CACHE_KEY = "latest_v1"

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        *,
        config: QuantConfig | None = None,
        universe_config: AutoUniverseConfig | None = None,
        universe_service: QuantUniverseService | None = None,
    ) -> None:
        self.cache_manager = cache_manager or CacheManager()
        self.config = config or QuantConfig()
        self.universe_config = universe_config or AutoUniverseConfig(
            source_limit=250,
            shortlist_limit=100,
        )
        self.universe_service = universe_service or QuantUniverseService(
            self.cache_manager,
            config=self.universe_config,
        )

    # -------------------------------------------------------------- market data

    def download_daily_frames(
        self,
        tickers: Sequence[str],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Fetch daily history in chunks, reporting progress and honouring cancellation."""

        symbols = normalize_tickers(tickers, limit=max(len(tickers), 1))
        frames: dict[str, Any] = {}
        errors: dict[str, str] = {}
        if not symbols:
            return frames, errors
        chunk_size = max(1, int(self.config.download_chunk))
        completed = 0
        for start in range(0, len(symbols), chunk_size):
            if cancel is not None and cancel():
                raise ScanCancelled("Quant scan cancelled")
            chunk = symbols[start : start + chunk_size]
            if progress is not None:
                progress(completed, len(symbols), chunk[0])
            try:
                with YF_LOCK:
                    downloaded = yf.download(
                        chunk,
                        period=self.config.history_period,
                        interval="1d",
                        auto_adjust=True,
                        prepost=False,
                        progress=False,
                        threads=True,
                        group_by="column",
                    )
                frames.update(SignalMarketDataService.split_download_frame(downloaded, chunk))
            except Exception as exc:
                logger.warning("Quant history download failed for %s: %s", ",".join(chunk), exc)
                for ticker in chunk:
                    errors[ticker] = str(exc)
            completed += len(chunk)
            if progress is not None:
                progress(completed, len(symbols), chunk[-1])
        for ticker in symbols:
            if ticker not in frames and ticker not in errors:
                errors[ticker] = "No daily history returned."
        return frames, errors

    # -------------------------------------------------------------- scanning

    def run_scan(
        self,
        *,
        force_universe_refresh: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> QuantScanPayload:
        """Source a universe, score every name, then discover pairs from the same history."""

        started_at = dt.datetime.now()
        if cancel is not None and cancel():
            raise ScanCancelled("Quant scan cancelled")
        universe = self.universe_service.source_candidates(force_refresh=force_universe_refresh)
        candidates: list[AutoTickerCandidate] = list(universe.get("candidates") or [])
        if not candidates:
            raise ValueError("No liquid US equities passed the automatic universe filters")
        by_ticker = {candidate.ticker: candidate for candidate in candidates}
        frames, errors = self.download_daily_frames(
            list(by_ticker),
            progress=progress,
            cancel=cancel,
        )
        if cancel is not None and cancel():
            raise ScanCancelled("Quant scan cancelled")
        rows: list[QuantScreenRow] = []
        for ticker, candidate in by_ticker.items():
            frame = frames.get(ticker)
            if frame is None:
                continue
            metrics = screen_metrics(frame, config=self.config)
            if not metrics.get("observations"):
                errors.setdefault(ticker, "No usable close history.")
                continue
            rows.append(
                QuantScreenRow(
                    ticker=ticker,
                    name=candidate.name,
                    exchange=candidate.exchange,
                    market_cap=_optional_float(candidate.market_cap),
                    last_price=metrics["last_price"],
                    median_dollar_volume=(
                        metrics["median_dollar_volume"]
                        if metrics["median_dollar_volume"] is not None
                        else _optional_float(candidate.median_dollar_volume)
                    ),
                    momentum_1m=metrics["momentum_1m"],
                    momentum_3m=metrics["momentum_3m"],
                    momentum_6m=metrics["momentum_6m"],
                    momentum_12m=metrics["momentum_12m"],
                    volatility_pct=metrics["volatility_pct"],
                    sharpe=metrics["sharpe"],
                    max_drawdown_pct=metrics["max_drawdown_pct"],
                    z_score=metrics["z_score"],
                    rsi=metrics["rsi"],
                    observations=int(metrics["observations"]),
                )
            )
        if not rows:
            raise ValueError("No ticker returned usable daily history for the Quant screen")
        ranked = rank_screen_rows(rows)
        if cancel is not None and cancel():
            raise ScanCancelled("Quant scan cancelled")
        # Pair discovery runs on the most liquid slice so the combination count stays sane.
        pair_universe = sorted(
            ranked,
            key=lambda row: -(row.median_dollar_volume or 0.0),
        )[: max(2, self.config.pair_universe_limit)]
        closes = {}
        for row in pair_universe:
            close, _ = _close_volume(frames.get(row.ticker))
            if not close.empty:
                closes[row.ticker] = close
        pairs = discover_pairs(closes, config=self.config)
        payload = QuantScanPayload(
            rows=ranked,
            pairs=pairs,
            source=str(universe.get("source") or "Yahoo Finance"),
            sourced_at=self._parse_datetime(universe.get("sourced_at")) or started_at,
            started_at=started_at,
            completed_at=dt.datetime.now(),
            universe_size=len(candidates),
            errors=errors,
            universe_from_cache=bool(universe.get("from_cache", False)),
        )
        self.save_latest_payload(payload)
        return payload

    def analyze_pair(self, left: str, right: str) -> dict[str, Any]:
        """Build the full detail view for one pair, including the relationship outputs."""

        left_symbol = str(left or "").upper().strip()
        right_symbol = str(right or "").upper().strip()
        if not left_symbol or not right_symbol:
            raise ValueError("Enter two ticker symbols.")
        if left_symbol == right_symbol:
            raise ValueError("Choose two different ticker symbols.")
        frames, errors = self.download_daily_frames([left_symbol, right_symbol])
        missing = [symbol for symbol in (left_symbol, right_symbol) if symbol not in frames]
        if missing:
            detail = errors.get(missing[0], "no daily history returned")
            raise ValueError(f"Could not load history for {', '.join(missing)}: {detail}")
        left_close, _ = _close_volume(frames[left_symbol])
        right_close, _ = _close_volume(frames[right_symbol])
        spread_info = build_pair_spread(left_close, right_close, z_window=self.config.spread_z_window)
        if spread_info["spread"].empty:
            raise ValueError("The selected tickers have too little overlapping history to model.")
        reversion = mean_reversion_stats(spread_info["spread"])
        hurst = hurst_exponent(spread_info["spread"])
        relationship = build_relationship_analysis(frames[left_symbol], frames[right_symbol])
        stats = {
            "correlation": spread_info["correlation"],
            "half_life": reversion["half_life"],
            "dickey_fuller": reversion["dickey_fuller"],
            "hurst": hurst,
        }
        return {
            "left": left_symbol,
            "right": right_symbol,
            "spread": spread_info["spread"],
            "spread_z": spread_info["spread_z"],
            "hedge_ratio": spread_info["hedge_ratio"],
            "intercept": spread_info["intercept"],
            "latest_z": spread_info["latest_z"],
            "correlation": spread_info["correlation"],
            "half_life": reversion["half_life"],
            "dickey_fuller": reversion["dickey_fuller"],
            "stationary_at": reversion["stationary_at"],
            "hurst": hurst,
            "score": score_pair(stats),
            "observations": spread_info["observations"],
            "indexed": relationship["indexed"],
            "rolling_correlation": relationship["rolling_correlation"],
        }

    # -------------------------------------------------------------- caching

    def save_latest_payload(self, payload: QuantScanPayload) -> None:
        self.cache_manager.save_json_payload(
            self._RESULT_NAMESPACE,
            self._RESULT_CACHE_KEY,
            self.payload_to_dict(payload),
        )

    def load_latest_payload(self) -> QuantScanPayload | None:
        value = self.cache_manager.get_json_payload(
            self._RESULT_NAMESPACE,
            self._RESULT_CACHE_KEY,
            max_age_seconds=self.config.result_cache_seconds,
            allow_stale=False,
        )
        return self.payload_from_dict(value) if isinstance(value, dict) else None

    @classmethod
    def payload_to_dict(cls, payload: QuantScanPayload) -> dict[str, Any]:
        return {
            "rows": [row.to_dict() for row in payload.rows],
            "pairs": [row.to_dict() for row in payload.pairs],
            "source": payload.source,
            "sourced_at": payload.sourced_at.isoformat(),
            "started_at": payload.started_at.isoformat(),
            "completed_at": payload.completed_at.isoformat(),
            "universe_size": int(payload.universe_size),
            "errors": dict(payload.errors),
            "universe_from_cache": bool(payload.universe_from_cache),
        }

    @classmethod
    def payload_from_dict(cls, value: Mapping[str, Any]) -> QuantScanPayload:
        return QuantScanPayload(
            rows=[
                QuantScreenRow.from_dict(item)
                for item in value.get("rows", [])
                if isinstance(item, Mapping)
            ],
            pairs=[
                QuantPairRow.from_dict(item)
                for item in value.get("pairs", [])
                if isinstance(item, Mapping)
            ],
            source=str(value.get("source") or "Yahoo Finance"),
            sourced_at=cls._parse_datetime(value.get("sourced_at")) or dt.datetime.now(),
            started_at=cls._parse_datetime(value.get("started_at")) or dt.datetime.now(),
            completed_at=cls._parse_datetime(value.get("completed_at")) or dt.datetime.now(),
            universe_size=int(value.get("universe_size") or 0),
            errors={str(key): str(item) for key, item in dict(value.get("errors") or {}).items()},
            universe_from_cache=bool(value.get("universe_from_cache", False)),
        )

    @staticmethod
    def _parse_datetime(value: Any) -> dt.datetime | None:
        try:
            return dt.datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
