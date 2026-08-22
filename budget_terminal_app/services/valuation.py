from __future__ import annotations

import math
import statistics
from typing import Any


DEFAULT_VALUATION_ASSUMPTIONS: dict[str, float | int | str] = {
    'basis_type': 'FCF',
    'basis_value': 0.0,
    'growth_1_5': 10.0,
    'growth_6_10': 5.0,
    'discount_rate': 10.0,
    'terminal_method': 'gordon_growth',
    'terminal_growth': 2.5,
    'exit_multiple': 15.0,
    'projection_years': 10,
    'margin_of_safety': 20.0,
}

_NUMERIC_FIELDS = (
    'basis_value',
    'growth_1_5',
    'growth_6_10',
    'discount_rate',
    'terminal_growth',
    'exit_multiple',
    'projection_years',
    'margin_of_safety',
)

#: Equity risk premium used by the CAPM required return. This is a judgement constant, not a
#: fetched series: Damodaran's implied US ERP has oscillated roughly 4.0-5.5% over the last
#: decade, and 5.0 is the round midpoint. Every derived required return moves one-for-one with
#: it, which is why it is named here rather than buried in the formula.
EQUITY_RISK_PREMIUM_PCT = 5.0

#: Minimum required-return-minus-terminal-growth spread the derivation targets in the BASE case.
#: ``_input_warnings`` blocks below 1.0, but ``_scenario_assumptions`` builds the bull case with
#: ``discount_rate - 1.0`` and ``terminal_growth + 0.5`` — narrowing the spread by 1.5 points. A
#: base spread under 1.0 + 1.5 therefore yields an unsolvable bull case, which flips
#: ``scenarios_ordered`` off and drops the whole verdict, even though the base case looks fine.
MIN_GORDON_SPREAD_PCT = 2.5

#: Extra slack on top of the arithmetic minimum. The assumption spin boxes carry one decimal, so
#: a derived terminal growth can round up 0.05 while the required return rounds down 0.05; that
#: 0.1 of shrinkage plus binary-float slop must not be allowed to eat into the spread.
_SPREAD_SAFETY_PCT = 0.2

#: Fallback anchors. These reproduce the pre-CAPM behaviour exactly, so losing the market
#: snapshot is a no-op rather than a regression.
HEURISTIC_BASELINE_RETURN_PCT = 10.0
DEFAULT_TERMINAL_GROWTH_PCT = 2.5
DEFAULT_EXIT_MULTIPLE = 15.0

#: Blume adjustment: Yahoo's five-year monthly beta is noisy at the tails, and an unadjusted 0.15
#: or 3.4 produces a required return that the clamps then silently rewrite.
_BLUME_WEIGHT = 0.67
_BETA_BOUNDS = (0.5, 2.5)

_EXIT_MULTIPLE_BOUNDS = (3.0, 50.0)
_MIN_PEER_COUNT = 3

#: Weight given to the analyst leg when blending with reported history. The long-term (+5y)
#: estimate covers exactly the years 1-5 horizon, so it earns more weight than a single fiscal year.
_ANALYST_LONG_TERM_WEIGHT = 0.60
_ANALYST_NEXT_YEAR_WEIGHT = 0.40

#: Yahoo emits absurd growth figures off a near-zero prior-year base; treat those as data errors.
_MAX_ANALYST_GROWTH_PCT = 100.0


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _clamp(value: Any, minimum: float, maximum: float) -> float:
    return min(max(float(value), minimum), maximum)


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    numeric = _safe_float(value, default)
    return min(max(float(default if numeric is None else numeric), minimum), maximum)


def normalize_valuation_assumptions(values: Any) -> dict[str, Any]:
    """Normalize persisted/UI assumptions to the supported valuation contract."""
    saved = values if isinstance(values, dict) else {}
    basis_type = str(saved.get('basis_type', 'FCF') or 'FCF').upper().strip()
    if basis_type not in {'FCF', 'EPS'}:
        basis_type = 'FCF'
    terminal_method = str(saved.get('terminal_method', 'gordon_growth') or '').lower().strip()
    terminal_method = terminal_method.replace(' ', '_')
    if terminal_method not in {'gordon_growth', 'exit_multiple'}:
        terminal_method = 'gordon_growth'
    try:
        years = int(saved.get('projection_years', 10))
    except (TypeError, ValueError, OverflowError):
        years = 10
    return {
        'basis_type': basis_type,
        'basis_value': _bounded_float(saved.get('basis_value', 0.0), 0.0, 0.0, 100000.0),
        'growth_1_5': _bounded_float(saved.get('growth_1_5', 10.0), 10.0, -30.0, 50.0),
        'growth_6_10': _bounded_float(saved.get('growth_6_10', 5.0), 5.0, -15.0, 30.0),
        'discount_rate': _bounded_float(saved.get('discount_rate', 10.0), 10.0, 4.0, 30.0),
        'terminal_method': terminal_method,
        'terminal_growth': _bounded_float(saved.get('terminal_growth', 2.5), 2.5, -2.0, 5.0),
        'exit_multiple': _bounded_float(saved.get('exit_multiple', 15.0), 15.0, 3.0, 50.0),
        'projection_years': min(max(years, 5), 15),
        'margin_of_safety': _bounded_float(saved.get('margin_of_safety', 20.0), 20.0, 0.0, 50.0),
    }


def _input_warnings(raw: Any, values: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if isinstance(raw, dict):
        for field in _NUMERIC_FIELDS:
            if field in raw and _safe_float(raw.get(field)) is None:
                warnings.append(f'{field.replace("_", " ").title()} must be a finite number.')
    if values['basis_value'] <= 0:
        warnings.append('Starting FCF/share or EPS must be greater than zero.')
    if values['basis_type'] == 'FCF' and values['terminal_method'] == 'gordon_growth':
        spread = float(values['discount_rate']) - float(values['terminal_growth'])
        if spread < 1.0:
            warnings.append('Required return must exceed Gordon terminal growth by at least 1 percentage point.')
    return warnings


def calculate_fair_value_details(assumptions: Any) -> dict[str, Any]:
    """Calculate fair value and auditable components without any UI dependencies."""
    values = normalize_valuation_assumptions(assumptions)
    warnings = _input_warnings(assumptions, values)
    basis_type = values['basis_type']
    requested_method = values['terminal_method']
    method = requested_method if basis_type == 'FCF' else 'earnings_multiple'
    result = {
        'fair_value': None,
        'explicit_forecast_pv': None,
        'terminal_pv': None,
        'terminal_value_share': None,
        'method': method,
        'requested_terminal_method': requested_method,
        'warnings': warnings,
        'assumptions': values,
        'projected_basis': [],
    }
    if warnings:
        return result

    required_return = float(values['discount_rate']) / 100.0
    growth_1_5 = float(values['growth_1_5']) / 100.0
    growth_6_10 = float(values['growth_6_10']) / 100.0
    years = int(values['projection_years'])
    current = float(values['basis_value'])
    projected: list[float] = []
    for year in range(1, years + 1):
        current *= 1.0 + (growth_1_5 if year <= 5 else growth_6_10)
        projected.append(current)

    if basis_type == 'EPS':
        explicit_pv = 0.0
        terminal_pv = projected[-1] * float(values['exit_multiple']) / ((1.0 + required_return) ** years)
    else:
        explicit_pv = sum(value / ((1.0 + required_return) ** year) for year, value in enumerate(projected, 1))
        if requested_method == 'gordon_growth':
            terminal_growth = float(values['terminal_growth']) / 100.0
            terminal_value = projected[-1] * (1.0 + terminal_growth) / (required_return - terminal_growth)
        else:
            terminal_value = projected[-1] * float(values['exit_multiple'])
        terminal_pv = terminal_value / ((1.0 + required_return) ** years)

    fair_value = explicit_pv + terminal_pv
    if not math.isfinite(fair_value) or fair_value <= 0:
        result['warnings'].append('The selected assumptions do not produce a positive finite fair value.')
        return result
    result.update({
        'fair_value': fair_value,
        'explicit_forecast_pv': explicit_pv,
        'terminal_pv': terminal_pv,
        'terminal_value_share': terminal_pv / fair_value,
        'projected_basis': projected,
    })
    return result


def calculate_fair_value_per_share(assumptions: Any) -> float | None:
    """Compatibility helper returning only the calculated per-share value."""
    return calculate_fair_value_details(assumptions)['fair_value']


def _scenario_assumptions(base: dict[str, Any], case: str) -> dict[str, Any]:
    if case == 'bear':
        values = {
            **base,
            'growth_1_5': float(base['growth_1_5']) - 5.0,
            'growth_6_10': float(base['growth_6_10']) - 3.0,
            'discount_rate': float(base['discount_rate']) + 2.0,
        }
        if base['terminal_method'] == 'gordon_growth':
            values['terminal_growth'] = float(base['terminal_growth']) - 0.5
        else:
            values['exit_multiple'] = float(base['exit_multiple']) * 0.8
        return values
    if case == 'bull':
        values = {
            **base,
            'growth_1_5': float(base['growth_1_5']) + 5.0,
            'growth_6_10': float(base['growth_6_10']) + 3.0,
            'discount_rate': float(base['discount_rate']) - 1.0,
        }
        if base['terminal_method'] == 'gordon_growth':
            values['terminal_growth'] = float(base['terminal_growth']) + 0.5
        else:
            values['exit_multiple'] = float(base['exit_multiple']) * 1.2
        return values
    return dict(base)


def _model_quality(
    base: dict[str, Any],
    details: dict[str, Any],
    history_points: int,
    ordered: bool,
    material_warnings: list[str],
) -> str | None:
    if details['fair_value'] is None:
        return None
    terminal_share = details.get('terminal_value_share')
    warnings = list(details.get('warnings') or []) + material_warnings
    if (
        base['basis_type'] == 'EPS'
        or history_points < 3
        or (terminal_share is not None and terminal_share > 0.85)
        or warnings
    ):
        return 'Low'
    if (
        base['basis_type'] == 'FCF'
        and history_points >= 4
        and ordered
        and not warnings
        and terminal_share is not None
        and terminal_share <= 0.75
    ):
        return 'High'
    return 'Medium'


def calculate_valuation_scenarios(
    price: Any,
    assumptions: Any,
    *,
    history_points: int | None = None,
    material_warnings: list[str] | None = None,
    blocking_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate additive bear/base/bull cases, thresholds, and model quality.

    ``material_warnings`` qualify the model but leave the verdict standing. ``blocking_warnings``
    say the fair values cannot be compared to ``price`` at all - a quote and statements in
    different currencies, for instance. The scenario fair values still come back, because the model
    itself is sound in its own unit, but every price-relative output (upside, the buy-below and
    trim-above thresholds, the verdict) is withheld and ``price_comparison_valid`` goes False.
    """
    base = normalize_valuation_assumptions(assumptions)
    if history_points is None and isinstance(assumptions, dict):
        raw_history_points = assumptions.get('comparable_history_points', 0)
        try:
            history_points = max(int(raw_history_points), 0)
        except (TypeError, ValueError):
            history_points = 0
    history_points = max(int(history_points or 0), 0)
    material_warnings = list(material_warnings or [])
    comparison_warnings = [str(item) for item in list(blocking_warnings or []) if str(item or '').strip()]
    price_comparison_valid = not comparison_warnings
    rows = []
    for name, key in (('Bear Case', 'bear'), ('Base Case', 'base'), ('Bull Case', 'bull')):
        scenario_values = _scenario_assumptions(base, key)
        details = calculate_fair_value_details(scenario_values)
        price_value = _safe_float(price)
        fair_value = details['fair_value']
        upside = (
            (fair_value / price_value - 1.0) * 100.0
            if price_comparison_valid and fair_value is not None and price_value and price_value > 0
            else None
        )
        rows.append({
            'name': name,
            'fair_value': fair_value,
            'upside_pct': upside,
            'assumptions': details['assumptions'],
            'components': {
                'explicit_forecast_pv': details['explicit_forecast_pv'],
                'terminal_pv': details['terminal_pv'],
                'terminal_value_share': details['terminal_value_share'],
                'method': details['method'],
            },
            'warnings': details['warnings'],
        })

    bear_value, base_value, bull_value = (row['fair_value'] for row in rows)
    ordered = all(value is not None for value in (bear_value, base_value, bull_value)) and bear_value <= base_value <= bull_value
    base_details = calculate_fair_value_details(assumptions)
    verdict_blockers = list(base_details['warnings']) + comparison_warnings
    warnings = list(base_details['warnings']) + comparison_warnings + material_warnings
    if not ordered and base_value is not None:
        ordering_warning = 'Bear, base, and bull values are not ordered; review the assumptions.'
        warnings.append(ordering_warning)
        verdict_blockers.append(ordering_warning)
    margin = float(base['margin_of_safety']) / 100.0
    buy_below = base_value * (1.0 - margin) if base_value is not None and price_comparison_valid else None
    price_value = _safe_float(price)
    verdict = None
    if not verdict_blockers and price_value is not None and price_value > 0 and buy_below is not None and bull_value is not None:
        if price_value < buy_below:
            verdict = 'Undervalued'
        elif price_value > bull_value:
            verdict = 'Overvalued'
        else:
            verdict = 'Fairly valued'
    return {
        'assumptions': base,
        'scenarios': rows,
        'base_fair_value': base_value,
        'buy_below': buy_below,
        'upper_scenario': bull_value if price_comparison_valid else None,
        'trim_above': bull_value if price_comparison_valid else None,
        'verdict': verdict,
        'warnings': warnings,
        'price_comparison_valid': price_comparison_valid,
        'blocking_warnings': comparison_warnings,
        'components': {
            'explicit_forecast_pv': base_details['explicit_forecast_pv'],
            'terminal_pv': base_details['terminal_pv'],
            'terminal_value_share': base_details['terminal_value_share'],
            'method': base_details['method'],
        },
        'scenario_assumptions': {row['name']: row['assumptions'] for row in rows},
        'scenarios_ordered': ordered,
        'model_quality': _model_quality(base, base_details, history_points, ordered, material_warnings + comparison_warnings),
        'comparable_history_points': history_points,
    }


def _three_year_cagr(values: Any, labels: Any = None) -> float | None:
    series = list(values or [])
    if len(series) < 4:
        return None
    numeric = [_safe_float(value) for value in series[-4:]]
    if any(value is None or value <= 0 for value in numeric):
        return None
    if labels is not None:
        years = []
        for label in list(labels or [])[-4:]:
            try:
                years.append(int(str(label)[:4]))
            except (TypeError, ValueError):
                return None
        if len(years) != 4 or any(right - left != 1 for left, right in zip(years, years[1:])):
            return None
    return ((float(numeric[-1]) / float(numeric[0])) ** (1.0 / 3.0) - 1.0) * 100.0


def _blume_beta(beta_raw: float | None) -> float:
    """Pull a raw beta toward 1.0 and bound it, so one noisy estimate cannot dominate CAPM."""
    if beta_raw is None:
        return 1.0
    adjusted = _BLUME_WEIGHT * float(beta_raw) + (1.0 - _BLUME_WEIGHT)
    return _clamp(adjusted, *_BETA_BOUNDS)


def _size_premium_pct(market_cap: float | None) -> float:
    """Small companies carry risk that beta alone does not price; approximate the decile spread."""
    if market_cap is None or market_cap >= 10_000_000_000.0:
        return 0.0
    if market_cap >= 2_000_000_000.0:
        return 0.5
    if market_cap >= 300_000_000.0:
        return 1.0
    return 2.0


def _leverage_premium_pct(net_debt: float | None, market_cap: float | None) -> tuple[float, float | None]:
    if net_debt is None or market_cap is None or market_cap <= 0:
        return 0.0, None
    leverage = net_debt / market_cap
    return (2.0 if leverage > 0.5 else 1.0 if leverage > 0.2 else 0.0), leverage


def estimate_required_return(metrics: Any, market: Any = None) -> dict[str, Any]:
    """Return a CAPM required return anchored to the live risk-free rate, with every term itemized.

    Falls back to the previous company-risk heuristic — identical arithmetic, identical output —
    whenever ``market`` carries no usable risk-free rate, so a failed Treasury fetch costs
    precision rather than correctness.
    """
    metrics = metrics if isinstance(metrics, dict) else {}
    market = market if isinstance(market, dict) else {}
    adjustments: list[dict[str, Any]] = []
    beta = _safe_float(metrics.get('beta'))
    free_cash_flow = _safe_float(metrics.get('free_cash_flow'))
    net_debt = _safe_float(metrics.get('net_debt'))
    market_cap = _safe_float(metrics.get('market_cap'))
    risk_free_rate = _safe_float(market.get('risk_free_rate'))
    if metrics.get('currency_mismatch'):
        # net_debt is reported and market_cap is quoted. Dividing one by the other across a
        # currency split manufactures a leverage premium out of the exchange rate, so the term is
        # dropped. The size premium keeps market_cap, which is quoted on both sides of that test.
        net_debt = None

    if risk_free_rate is None:
        required_return = HEURISTIC_BASELINE_RETURN_PCT
        if beta is not None:
            adjustment = (beta - 1.0) * 2.0
            required_return += adjustment
            adjustments.append({'factor': 'Beta', 'adjustment_pct_points': adjustment, 'value': beta})
        beta_adjusted = None
        baseline = HEURISTIC_BASELINE_RETURN_PCT
        method = 'heuristic'
        source = '10% baseline plus beta, negative-FCF, and leverage adjustments'
        caveat = 'Heuristic required return; it is not a market-implied cost of equity.'
    else:
        beta_adjusted = _blume_beta(beta)
        equity_premium = beta_adjusted * EQUITY_RISK_PREMIUM_PCT
        size_premium = _size_premium_pct(market_cap)
        required_return = risk_free_rate + equity_premium + size_premium
        adjustments.append({
            'factor': 'Risk-free rate (10Y Treasury)',
            'adjustment_pct_points': risk_free_rate,
            'value': risk_free_rate,
        })
        adjustments.append({
            'factor': 'Beta x equity risk premium',
            'adjustment_pct_points': equity_premium,
            'value': beta_adjusted,
        })
        if size_premium:
            adjustments.append({
                'factor': 'Size premium',
                'adjustment_pct_points': size_premium,
                'value': market_cap,
            })
        baseline = risk_free_rate
        method = 'capm'
        source = (
            f'CAPM: {risk_free_rate:.2f}% 10Y Treasury + {beta_adjusted:.2f} adjusted beta '
            f'x {EQUITY_RISK_PREMIUM_PCT:.1f}% ERP, plus size, FCF, and leverage add-ons'
        )
        caveat = (
            f'The {EQUITY_RISK_PREMIUM_PCT:.1f}% equity risk premium is a fixed assumption, '
            'not a market-implied estimate.'
        )

    if free_cash_flow is not None and free_cash_flow <= 0:
        required_return += 1.5
        adjustments.append({'factor': 'Negative FCF', 'adjustment_pct_points': 1.5, 'value': free_cash_flow})
    leverage_premium, leverage = _leverage_premium_pct(net_debt, market_cap)
    if leverage_premium:
        required_return += leverage_premium
        adjustments.append({
            'factor': 'Net debt / market cap',
            'adjustment_pct_points': leverage_premium,
            'value': leverage,
        })
    return {
        'value': _clamp(required_return, 4.0, 30.0),
        'baseline': baseline,
        'method': method,
        'risk_free_rate': risk_free_rate,
        'as_of': str(market.get('as_of') or '') or None,
        'equity_risk_premium': EQUITY_RISK_PREMIUM_PCT if method == 'capm' else None,
        'beta_raw': beta,
        'beta_adjusted': beta_adjusted,
        'adjustments': adjustments,
        'source': source,
        'caveat': caveat,
    }


def _terminal_growth_pct(market: Any, required_return_pct: float) -> dict[str, Any]:
    """Anchor perpetual growth to market expectations, then cap it so every scenario stays solvable."""
    market = market if isinstance(market, dict) else {}
    risk_free_rate = _safe_float(market.get('risk_free_rate'))
    breakeven = _safe_float(market.get('breakeven_inflation'))
    if breakeven is not None and breakeven > 0:
        value = breakeven
        source = f'10Y breakeven inflation ({breakeven:.2f}%)'
    elif risk_free_rate is not None:
        value = min(risk_free_rate, DEFAULT_TERMINAL_GROWTH_PCT)
        source = (
            f'Lesser of the {risk_free_rate:.2f}% 10Y Treasury yield and the '
            f'{DEFAULT_TERMINAL_GROWTH_PCT:.1f}% mature-growth anchor'
        )
    else:
        value = DEFAULT_TERMINAL_GROWTH_PCT
        source = 'Independent mature-growth anchor'

    caps: list[str] = []
    if risk_free_rate is not None and value > risk_free_rate:
        value = risk_free_rate
        caps.append('capped at the 10Y Treasury yield')
    spread_cap = float(required_return_pct) - (MIN_GORDON_SPREAD_PCT + _SPREAD_SAFETY_PCT)
    if value > spread_cap:
        value = spread_cap
        caps.append(
            f'held {MIN_GORDON_SPREAD_PCT:.1f}pp under the required return so the bull case stays solvable'
        )
    return {
        'value': _clamp(value, -2.0, 5.0),
        'source': source + (' — ' + '; '.join(caps) if caps else ''),
        'risk_free_rate': risk_free_rate,
        'breakeven_inflation': breakeven,
        'caps_applied': caps,
    }


def _analyst_growth_pct(analyst: Any) -> dict[str, Any] | None:
    """Pick the best-horizon analyst growth figure, or ``None`` when none is usable."""
    data = analyst if isinstance(analyst, dict) else {}
    for key, weight, label in (
        ('long_term_growth_pct', _ANALYST_LONG_TERM_WEIGHT, 'analyst long-term (+5y) growth'),
        ('next_year_growth_pct', _ANALYST_NEXT_YEAR_WEIGHT, 'analyst next-year growth'),
    ):
        value = _safe_float(data.get(key))
        if value is None or abs(value) > _MAX_ANALYST_GROWTH_PCT:
            continue
        return {'value': value, 'weight': weight, 'label': label}
    return None


def _blend_near_growth(
    historical: float | None,
    candidates: list[tuple[str, float]],
    estimate: dict[str, Any] | None,
) -> tuple[float, str, list[dict[str, Any]]]:
    inputs = [{'name': name, 'value': value} for name, value in candidates]
    if estimate is not None:
        inputs.append({'name': estimate['label'], 'value': estimate['value']})
    history_label = 'median of ' + ', '.join(name for name, _ in candidates) if candidates else ''
    if estimate is not None and historical is not None:
        weight = float(estimate['weight'])
        value = weight * float(estimate['value']) + (1.0 - weight) * historical
        source = (
            f'{weight * 100:.0f}% {estimate["label"]} ({estimate["value"]:.1f}%) blended with '
            f'{(1.0 - weight) * 100:.0f}% {history_label} ({historical:.1f}%)'
        )
    elif estimate is not None:
        value = float(estimate['value'])
        source = f'{estimate["label"]} ({estimate["value"]:.1f}%); no usable annual history'
    elif historical is not None:
        value = historical
        source = 'Median of ' + ', '.join(name for name, _ in candidates)
    else:
        value = float(DEFAULT_VALUATION_ASSUMPTIONS['growth_1_5'])
        source = f'No usable growth inputs; held at the {value:.1f}% default'
    return _clamp(value, -30.0, 50.0), source, inputs


def _fade_growth(near_pct: float, terminal_pct: float, projection_years: int) -> float:
    """Average of a linear fade from near-term growth at year 5 to terminal growth at year N.

    The DCF charges a single flat rate across years 6..N, so the honest stand-in for a fade is
    its mean over that tail rather than either endpoint. The closed form is exact.
    """
    tail = int(projection_years) - 5
    if tail <= 0:
        return float(terminal_pct)
    weight = (int(projection_years) - 4) / (2.0 * tail)
    return float(near_pct) + (float(terminal_pct) - float(near_pct)) * weight


def _peer_exit_multiple(peer_rows: Any, basis_type: str, anchor_ticker: Any = None) -> dict[str, Any] | None:
    """Median peer equity multiple matched to the model's per-share flow, or ``None``.

    The DCF multiplies a per-share flow, so the multiple has to be an equity multiple.
    ``peer_rows`` carries no P/FCF column, but ``100 / fcf_yield`` is exactly that; EV/EBITDA is
    deliberately unused because an enterprise multiple on a per-share equity flow is a unit error.
    """
    anchor = str(anchor_ticker or '').upper().strip()
    is_eps = str(basis_type or '').upper().strip() == 'EPS'
    low, high = _EXIT_MULTIPLE_BOUNDS
    inputs: list[dict[str, Any]] = []
    for row in list(peer_rows or []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('ticker') or '').upper().strip()
        if str(row.get('source') or '') == 'Loaded' or (anchor and symbol == anchor):
            continue
        if is_eps:
            multiple = _safe_float(row.get('pe'))
            if multiple is None or multiple <= 0:
                multiple = _safe_float(row.get('forward_pe'))
        else:
            fcf_yield = _safe_float(row.get('fcf_yield'))
            multiple = 100.0 / fcf_yield if fcf_yield is not None and fcf_yield > 0 else None
        if multiple is None or multiple <= 0 or multiple < low or multiple > high:
            continue
        inputs.append({'ticker': symbol or '?', 'value': multiple})
    if len(inputs) < _MIN_PEER_COUNT:
        return None
    label = 'P/E' if is_eps else 'P/FCF'
    excluded = f' ({anchor} excluded)' if anchor else ''
    return {
        'value': _clamp(statistics.median(item['value'] for item in inputs), low, high),
        'source': f'Median {label} of {len(inputs)} peers{excluded}',
        'peer_count': len(inputs),
        'inputs': inputs,
    }


def _margin_of_safety_pct(
    *,
    basis_type: str,
    history_points: int,
    terminal_share: float | None,
    missing_inputs: list[str],
) -> dict[str, Any]:
    """Size the discount to fair value from how much of the model is supported by real data.

    The thresholds mirror ``_model_quality`` rather than inventing a second notion of confidence.
    """
    reasons: list[str] = []
    margin = 15.0
    if history_points < 4:
        margin += 10.0
        reasons.append(f'{history_points} comparable annual periods')
    if history_points < 3:
        margin += 5.0
    if terminal_share is None or terminal_share > 0.75:
        margin += 10.0
        reasons.append(
            'terminal value is most of the answer'
            if terminal_share is not None
            else 'the model did not solve on the derived inputs'
        )
    if terminal_share is not None and terminal_share > 0.85:
        margin += 5.0
    if basis_type == 'EPS':
        margin += 5.0
        reasons.append('an EPS basis ignores capital intensity')
    if missing_inputs:
        margin += min(5.0 * len(missing_inputs), 10.0)
        reasons.append('missing ' + ', '.join(missing_inputs))
    detail = '; '.join(reasons) if reasons else 'every derivation input was available'
    return {
        'value': _clamp(margin, 0.0, 50.0),
        'source': f'Scaled to model support — {detail}',
        'reasons': reasons,
    }


def derive_valuation_suggestions(
    metrics: Any,
    trends: Any,
    basis_type: Any = 'FCF',
    *,
    market: Any = None,
    analyst: Any = None,
    peer_rows: Any = None,
    projection_years: Any = 10,
    terminal_method: Any = 'gordon_growth',
) -> dict[str, Any]:
    """Derive every assumption from reported history, market rates, analyst estimates, and peers.

    Each field is emitted as ``{'value', 'source'}`` so the page can explain itself, and the order
    below is load-bearing: the required return sets the terminal-growth cap, terminal growth sets
    the fade target, and the whole derived set is priced once to size the margin of safety.
    """
    metrics = metrics if isinstance(metrics, dict) else {}
    trends = trends if isinstance(trends, dict) else {}
    basis_type = 'EPS' if str(basis_type or '').upper().strip() == 'EPS' else 'FCF'
    try:
        years = min(max(int(projection_years), 5), 15)
    except (TypeError, ValueError, OverflowError):
        years = 10
    try:
        history_points = max(int(trends.get('comparable_history_points', 0) or 0), 0)
    except (TypeError, ValueError):
        history_points = 0

    fields: dict[str, Any] = {}
    caveats = [
        'Suggestions require consecutive, consistently positive annual history; '
        'invalid series are excluded in full.'
    ]
    missing_inputs: list[str] = []

    required = estimate_required_return(metrics, market)
    fields['discount_rate'] = required
    if required.get('method') != 'capm':
        missing_inputs.append('risk-free rate')
        caveats.append(
            'Risk-free rate unavailable; the required return falls back to the 10% heuristic baseline.'
        )

    terminal = _terminal_growth_pct(market, required['value'])
    fields['terminal_growth'] = terminal

    labels = trends.get('labels')
    basis_key = 'eps' if basis_type == 'EPS' else ('fcf_per_share' if trends.get('fcf_per_share') else 'fcf')
    candidates: list[tuple[str, float]] = []
    basis_cagr = _three_year_cagr(trends.get(basis_key), labels)
    if basis_cagr is not None:
        candidates.append((f'3-year {basis_type} CAGR', basis_cagr))
    revenue_cagr = _three_year_cagr(trends.get('revenue'), labels)
    if revenue_cagr is not None:
        candidates.append(('3-year revenue CAGR', revenue_cagr))
    latest_revenue_growth = _safe_float(metrics.get('revenue_growth'))
    if latest_revenue_growth is not None:
        candidates.append(('latest revenue growth', latest_revenue_growth))
    historical = statistics.median(value for _, value in candidates) if candidates else None
    estimate = _analyst_growth_pct(analyst)
    if estimate is None:
        missing_inputs.append('analyst estimates')
        caveats.append('Analyst estimates unavailable; near-term growth uses reported history only.')
    near_growth, growth_source, growth_inputs = _blend_near_growth(historical, candidates, estimate)
    fields['growth_1_5'] = {'value': near_growth, 'source': growth_source, 'inputs': growth_inputs}

    fields['growth_6_10'] = {
        'value': _clamp(_fade_growth(near_growth, terminal['value'], years), -15.0, 30.0),
        'source': (
            f'Average of a linear fade from {near_growth:.1f}% at year 5 to '
            f'{terminal["value"]:.1f}% at year {years}'
        ),
    }

    exit_multiple = _peer_exit_multiple(peer_rows, basis_type, metrics.get('ticker'))
    if exit_multiple is None:
        missing_inputs.append('peer multiples')
        caveats.append(
            f'Fewer than {_MIN_PEER_COUNT} usable peer multiples; '
            f'the exit multiple stays at the {DEFAULT_EXIT_MULTIPLE:.1f}x default.'
        )
        exit_multiple = {
            'value': DEFAULT_EXIT_MULTIPLE,
            'source': f'Default {DEFAULT_EXIT_MULTIPLE:.1f}x — too few usable peer multiples',
            'peer_count': 0,
            'inputs': [],
        }
    fields['exit_multiple'] = exit_multiple

    probe = calculate_fair_value_details({
        'basis_type': basis_type,
        'basis_value': metrics.get('basis_value'),
        'growth_1_5': fields['growth_1_5']['value'],
        'growth_6_10': fields['growth_6_10']['value'],
        'discount_rate': required['value'],
        'terminal_method': terminal_method,
        'terminal_growth': terminal['value'],
        'exit_multiple': exit_multiple['value'],
        'projection_years': years,
        'margin_of_safety': DEFAULT_VALUATION_ASSUMPTIONS['margin_of_safety'],
    })
    fields['margin_of_safety'] = _margin_of_safety_pct(
        basis_type=basis_type,
        history_points=history_points,
        terminal_share=probe.get('terminal_value_share'),
        missing_inputs=missing_inputs,
    )

    return {
        'basis_type': basis_type,
        'fields': fields,
        'caveats': caveats,
        'market': dict(market) if isinstance(market, dict) else None,
        'quality': {
            'history_points': history_points,
            'terminal_value_share': probe.get('terminal_value_share'),
            'missing_inputs': missing_inputs,
        },
    }
