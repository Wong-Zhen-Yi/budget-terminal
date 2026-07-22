from __future__ import annotations

import datetime
import math
from statistics import NormalDist
from typing import Any


def _option_time(expiry: str, today: datetime.date | None = None) -> float | None:
    try:
        expiry_date = datetime.datetime.strptime(expiry, "%Y-%m-%d").date()
    except ValueError:
        return None
    current_date = today or datetime.date.today()
    return max((expiry_date - current_date).days, 0) / 365.0 or 1.0 / 365.0


def implied_volatility(
    spot: float,
    strike: float,
    expiry: str,
    risk_free_rate: float,
    dividend_yield: float,
    market_price: float,
    option_type: str,
    *,
    today: datetime.date | None = None,
) -> float:
    if market_price <= 0 or spot <= 0 or strike <= 0 or option_type not in {"call", "put"}:
        return 0.0
    time_to_expiry = _option_time(expiry, today)
    if time_to_expiry is None:
        return 0.0
    rate = min(max(float(risk_free_rate), 0.0), 1.0)
    dividend = min(max(float(dividend_yield), 0.0), 1.0)
    normal = NormalDist()
    discounted_dividend = math.exp(-dividend * time_to_expiry)
    discounted_rate = math.exp(-rate * time_to_expiry)
    sqrt_time = math.sqrt(time_to_expiry)
    sigma = 0.3
    for _ in range(30):
        denominator = sigma * sqrt_time
        if denominator <= 0:
            return 0.0
        d1 = (
            math.log(spot / strike)
            + (rate - dividend + 0.5 * sigma * sigma) * time_to_expiry
        ) / denominator
        d2 = d1 - denominator
        if option_type == "call":
            price = spot * discounted_dividend * normal.cdf(d1) - strike * discounted_rate * normal.cdf(d2)
        else:
            price = strike * discounted_rate * normal.cdf(-d2) - spot * discounted_dividend * normal.cdf(-d1)
        vega = spot * discounted_dividend * normal.pdf(d1) * sqrt_time
        if vega < 1e-12:
            break
        sigma = max(0.001, min(sigma - (price - market_price) / vega, 10.0))
        if abs(price - market_price) < 0.001:
            return sigma
    return 0.0


def empty_greeks() -> dict[str, Any]:
    return {
        "delta_calc": None,
        "gamma_calc": None,
        "theta_calc": None,
        "vega_calc": None,
        "rho_calc": None,
        "greeks_valid": False,
    }


def calculate_greeks(
    spot: float,
    strike: float,
    expiry: str,
    volatility: float,
    option_type: str,
    risk_free_rate: float,
    dividend_yield: float,
    *,
    today: datetime.date | None = None,
) -> dict[str, Any]:
    if spot <= 0 or strike <= 0 or volatility <= 0 or option_type not in {"call", "put"}:
        return empty_greeks()
    time_to_expiry = _option_time(expiry, today)
    if time_to_expiry is None:
        return empty_greeks()
    sigma = float(volatility)
    sqrt_time = math.sqrt(time_to_expiry)
    denominator = sigma * sqrt_time
    if denominator <= 0:
        return empty_greeks()
    rate = min(max(float(risk_free_rate), 0.0), 1.0)
    dividend = min(max(float(dividend_yield), 0.0), 1.0)
    normal = NormalDist()
    discounted_dividend = math.exp(-dividend * time_to_expiry)
    discounted_rate = math.exp(-rate * time_to_expiry)
    d1 = (
        math.log(spot / strike)
        + (rate - dividend + 0.5 * sigma * sigma) * time_to_expiry
    ) / denominator
    d2 = d1 - denominator
    density = normal.pdf(d1)
    if option_type == "call":
        delta = discounted_dividend * normal.cdf(d1)
        theta_year = (
            -(spot * discounted_dividend * density * sigma) / (2 * sqrt_time)
            - rate * strike * discounted_rate * normal.cdf(d2)
            + dividend * spot * discounted_dividend * normal.cdf(d1)
        )
        rho = strike * time_to_expiry * discounted_rate * normal.cdf(d2) / 100.0
    else:
        delta = discounted_dividend * (normal.cdf(d1) - 1.0)
        theta_year = (
            -(spot * discounted_dividend * density * sigma) / (2 * sqrt_time)
            + rate * strike * discounted_rate * normal.cdf(-d2)
            - dividend * spot * discounted_dividend * normal.cdf(-d1)
        )
        rho = -strike * time_to_expiry * discounted_rate * normal.cdf(-d2) / 100.0
    return {
        "delta_calc": delta,
        "gamma_calc": discounted_dividend * density / (spot * denominator),
        "theta_calc": theta_year / 365.0,
        "vega_calc": spot * discounted_dividend * density * sqrt_time / 100.0,
        "rho_calc": rho,
        "greeks_valid": True,
    }


def extract_dividend_yield(info: Any) -> float | None:
    if not isinstance(info, dict):
        return None
    for key in ("dividendYield", "trailingAnnualDividendYield"):
        try:
            value = float(info.get(key))
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        if value > 1.0:
            value /= 100.0
        return min(max(value, 0.0), 1.0)
    return None
