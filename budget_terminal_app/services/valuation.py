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


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


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
) -> dict[str, Any]:
    """Calculate additive bear/base/bull cases, thresholds, and model quality."""
    base = normalize_valuation_assumptions(assumptions)
    if history_points is None and isinstance(assumptions, dict):
        raw_history_points = assumptions.get('comparable_history_points', 0)
        try:
            history_points = max(int(raw_history_points), 0)
        except (TypeError, ValueError):
            history_points = 0
    history_points = max(int(history_points or 0), 0)
    material_warnings = list(material_warnings or [])
    rows = []
    for name, key in (('Bear Case', 'bear'), ('Base Case', 'base'), ('Bull Case', 'bull')):
        scenario_values = _scenario_assumptions(base, key)
        details = calculate_fair_value_details(scenario_values)
        price_value = _safe_float(price)
        fair_value = details['fair_value']
        upside = (fair_value / price_value - 1.0) * 100.0 if fair_value is not None and price_value and price_value > 0 else None
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
    blocking_warnings = list(base_details['warnings'])
    warnings = list(blocking_warnings) + material_warnings
    if not ordered and base_value is not None:
        ordering_warning = 'Bear, base, and bull values are not ordered; review the assumptions.'
        warnings.append(ordering_warning)
        blocking_warnings.append(ordering_warning)
    margin = float(base['margin_of_safety']) / 100.0
    buy_below = base_value * (1.0 - margin) if base_value is not None else None
    price_value = _safe_float(price)
    verdict = None
    if not blocking_warnings and price_value is not None and price_value > 0 and buy_below is not None and bull_value is not None:
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
        'upper_scenario': bull_value,
        'trim_above': bull_value,
        'verdict': verdict,
        'warnings': warnings,
        'components': {
            'explicit_forecast_pv': base_details['explicit_forecast_pv'],
            'terminal_pv': base_details['terminal_pv'],
            'terminal_value_share': base_details['terminal_value_share'],
            'method': base_details['method'],
        },
        'scenario_assumptions': {row['name']: row['assumptions'] for row in rows},
        'scenarios_ordered': ordered,
        'model_quality': _model_quality(base, base_details, history_points, ordered, material_warnings),
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


def estimate_required_return(metrics: Any) -> dict[str, Any]:
    """Return a transparent company-risk heuristic and each adjustment."""
    metrics = metrics if isinstance(metrics, dict) else {}
    adjustments: list[dict[str, Any]] = []
    required_return = 10.0
    beta = _safe_float(metrics.get('beta'))
    if beta is not None:
        adjustment = (beta - 1.0) * 2.0
        required_return += adjustment
        adjustments.append({'factor': 'Beta', 'adjustment_pct_points': adjustment, 'value': beta})
    free_cash_flow = _safe_float(metrics.get('free_cash_flow'))
    if free_cash_flow is not None and free_cash_flow <= 0:
        required_return += 1.5
        adjustments.append({'factor': 'Negative FCF', 'adjustment_pct_points': 1.5, 'value': free_cash_flow})
    net_debt = _safe_float(metrics.get('net_debt'))
    market_cap = _safe_float(metrics.get('market_cap'))
    if net_debt is not None and market_cap is not None and market_cap > 0:
        leverage = net_debt / market_cap
        adjustment = 2.0 if leverage > 0.5 else 1.0 if leverage > 0.2 else 0.0
        if adjustment:
            required_return += adjustment
            adjustments.append({'factor': 'Net debt / market cap', 'adjustment_pct_points': adjustment, 'value': leverage})
    return {
        'value': min(max(required_return, 4.0), 30.0),
        'baseline': 10.0,
        'adjustments': adjustments,
        'source': '10% baseline plus beta, negative-FCF, and leverage adjustments',
        'caveat': 'Heuristic required return; it is not a market-implied cost of equity.',
    }


def derive_valuation_suggestions(metrics: Any, trends: Any, basis_type: Any = 'FCF') -> dict[str, Any]:
    """Derive auditable suggestions without stitching across invalid annual periods."""
    metrics = metrics if isinstance(metrics, dict) else {}
    trends = trends if isinstance(trends, dict) else {}
    basis_type = 'EPS' if str(basis_type or '').upper().strip() == 'EPS' else 'FCF'
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
    fields: dict[str, Any] = {}
    if candidates:
        near_growth = min(max(statistics.median(value for _, value in candidates), -30.0), 50.0)
        fields['growth_1_5'] = {
            'value': near_growth,
            'source': 'Median of ' + ', '.join(name for name, _ in candidates),
            'inputs': [{'name': name, 'value': value} for name, value in candidates],
        }
        fields['growth_6_10'] = {
            'value': min(max((near_growth + 2.5) / 2.0, -15.0), 30.0),
            'source': 'Halfway from near-term growth toward a 2.5% mature-growth anchor',
        }
    fields['terminal_growth'] = {
        'value': 2.5,
        'source': 'Independent mature-growth anchor',
    }
    fields['discount_rate'] = estimate_required_return(metrics)
    return {
        'basis_type': basis_type,
        'fields': fields,
        'caveats': ['Suggestions require consecutive, consistently positive annual history; invalid series are excluded in full.'],
    }
