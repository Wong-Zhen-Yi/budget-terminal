from __future__ import annotations

from typing import Any

from ..constants import SECTOR_DATA
from ..dependencies import *
from ..services.sec_edgar import fetch_company_bundle, merge_sec_frames
from ..services.valuation import (
    DEFAULT_VALUATION_ASSUMPTIONS as DEFAULT_VALUATION_ASSUMPTIONS,
    calculate_fair_value_details as calculate_fair_value_details,
    calculate_fair_value_per_share as calculate_fair_value_per_share,
    calculate_valuation_scenarios as calculate_valuation_scenarios,
    derive_valuation_suggestions,
    estimate_required_return as estimate_required_return,
    normalize_valuation_assumptions as normalize_valuation_assumptions,
)


PEER_ROW_LIMIT = 5
PEER_CANDIDATE_LIMIT = 16
PEER_CUSTOM_ROW_LIMIT = 12
DEFAULT_PEERS = ('MSFT', 'AAPL', 'GOOGL', 'AMZN')

INDUSTRY_PEER_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (('semiconductor', 'semiconductors', 'chip', 'integrated circuit'), ('NVDA', 'AMD', 'AVGO', 'QCOM', 'INTC', 'MU', 'TSM', 'ASML', 'MRVL')),
    (('software', 'cloud', 'infrastructure software', 'application software'), ('MSFT', 'ORCL', 'CRM', 'ADBE', 'NOW', 'INTU', 'SNOW', 'PANW', 'ADSK')),
    (('consumer electronics', 'computer hardware', 'communication equipment'), ('AAPL', 'SONY', 'DELL', 'HPQ', 'LOGI', 'CSCO', 'ANET')),
    (('internet content', 'internet information', 'interactive media', 'entertainment'), ('GOOGL', 'META', 'NFLX', 'SPOT', 'PINS', 'SNAP', 'DIS')),
    (('internet retail', 'specialty retail', 'e-commerce', 'auto manufacturers', 'automobiles'), ('AMZN', 'MELI', 'SHOP', 'EBAY', 'TSLA', 'TM', 'F', 'GM')),
    (('banks', 'bank', 'credit services'), ('JPM', 'BAC', 'WFC', 'C', 'USB', 'PNC', 'TFC', 'COF', 'AXP')),
    (('capital markets', 'asset management', 'financial data'), ('GS', 'MS', 'BLK', 'SCHW', 'CME', 'ICE', 'SPGI', 'MCO')),
    (('oil', 'gas', 'energy', 'exploration', 'integrated oil'), ('XOM', 'CVX', 'COP', 'EOG', 'OXY', 'SHEL', 'BP', 'TTE', 'SLB')),
    (('drug manufacturer', 'pharmaceutical', 'biotechnology', 'biotech'), ('LLY', 'NVO', 'JNJ', 'MRK', 'ABBV', 'PFE', 'BMY', 'AMGN', 'GILD', 'REGN')),
    (('medical', 'diagnostics', 'healthcare plans', 'medical devices'), ('UNH', 'ELV', 'CI', 'HUM', 'TMO', 'DHR', 'ABT', 'SYK', 'ISRG', 'MDT')),
    (('discount stores', 'grocery stores', 'household', 'beverages', 'packaged foods'), ('WMT', 'COST', 'TGT', 'DG', 'DLTR', 'KR', 'PG', 'KO', 'PEP', 'MDLZ')),
    (('home improvement', 'restaurants', 'apparel'), ('HD', 'LOW', 'MCD', 'SBUX', 'CMG', 'YUM', 'NKE', 'LULU', 'TJX')),
    (('reit', 'real estate'), ('PLD', 'AMT', 'EQIX', 'CCI', 'PSA', 'O', 'WELL', 'SPG', 'VICI')),
    (('utilities', 'utility', 'regulated electric'), ('NEE', 'DUK', 'SO', 'AEP', 'EXC', 'SRE', 'PEG', 'ED', 'XEL')),
    (('aerospace', 'defense'), ('RTX', 'LMT', 'NOC', 'GD', 'BA', 'GE', 'HON', 'TXT')),
    (('farm', 'machinery', 'industrial', 'specialty industrial'), ('CAT', 'DE', 'ETN', 'EMR', 'ITW', 'MMM', 'PH', 'ROK')),
)

SECTOR_ALIASES = {
    'technology': 'Technology',
    'financialservices': 'Financials',
    'financials': 'Financials',
    'healthcare': 'Healthcare',
    'consumercyclical': 'Consumer Cyclical',
    'consumerdefensive': 'Consumer Defensive',
    'communicationservices': 'Communication Services',
    'energy': 'Energy',
    'industrials': 'Industrials',
    'utilities': 'Utilities',
    'realestate': 'Real Estate',
    'basicmaterials': 'Basic Materials',
}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    try:
        if not math.isfinite(numeric) or pd.isna(numeric):
            return default
    except Exception:
        if not math.isfinite(numeric):
            return default
    return numeric


def _normalize_label(value: Any) -> str:
    return ''.join(char for char in str(value or '').lower() if char.isalnum())


def _statement_series(frame: Any, aliases: tuple[str, ...]) -> Any:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    alias_keys = tuple(_normalize_label(alias) for alias in aliases)
    rows = list(frame.index)
    for row in rows:
        row_key = _normalize_label(row)
        if row_key in alias_keys:
            result = frame.loc[row]
            return result.iloc[0] if isinstance(result, pd.DataFrame) else result
    for row in rows:
        row_key = _normalize_label(row)
        if any(alias_key and (alias_key in row_key or row_key in alias_key) for alias_key in alias_keys):
            result = frame.loc[row]
            return result.iloc[0] if isinstance(result, pd.DataFrame) else result
    return None


def _numeric_statement_values(frame: Any, aliases: tuple[str, ...]) -> Any:
    series = _statement_series(frame, aliases)
    if series is None:
        return None
    try:
        values = pd.to_numeric(series, errors='coerce').dropna()
    except Exception:
        return None
    return values if len(values) else None


def _latest_statement_value(frames: tuple[Any, ...], aliases: tuple[str, ...], *, flow: bool = False) -> float | None:
    for frame_index, frame in enumerate(frames):
        values = _numeric_statement_values(frame, aliases)
        if values is None or not len(values):
            continue
        ordered = []
        for column, value in values.items():
            try:
                sort_key = (1, pd.Timestamp(column).normalize())
            except (TypeError, ValueError):
                sort_key = (0, str(column))
            ordered.append((sort_key, value))
        ordered.sort(key=lambda item: item[0], reverse=True)
        if flow and frame_index == 0 and len(ordered) >= 4:
            return _safe_float(sum(value for _, value in ordered[:4]))
        return _safe_float(ordered[0][1])
    return None


def _latest_complete_quarter_sum(frame: Any, aliases: tuple[str, ...]) -> float | None:
    """Sum the latest four direct/derived quarters only when they are consecutive."""
    values = _numeric_statement_values(frame, aliases)
    if values is None or len(values) < 4:
        return None
    dated = []
    for column, value in values.items():
        try:
            dated.append((pd.Timestamp(column).normalize(), float(value)))
        except (TypeError, ValueError):
            continue
    dated.sort(key=lambda item: item[0], reverse=True)
    latest = dated[:4]
    if len(latest) != 4:
        return None
    gaps = [(latest[index][0] - latest[index + 1][0]).days for index in range(3)]
    if any(gap < 50 or gap > 140 for gap in gaps):
        return None
    return _safe_float(sum(value for _, value in latest))


def _reported_flow_value(quarterly: Any, annual: Any, aliases: tuple[str, ...]) -> float | None:
    """Resolve a reported flow as complete-quarter TTM, then latest annual."""
    ttm_value = _latest_complete_quarter_sum(quarterly, aliases)
    return ttm_value if ttm_value is not None else _latest_statement_value((annual,), aliases)


def _selected_sec_provenance(sec_bundle: dict[str, Any], row: str, *, flow: bool) -> dict[str, Any]:
    """Describe the SEC facts actually eligible for one valuation input."""
    provenance = sec_bundle.get('provenance') if isinstance(sec_bundle.get('provenance'), dict) else {}
    periods = provenance.get(row) if isinstance(provenance.get(row), dict) else {}
    quarterly = periods.get('quarterly') if isinstance(periods.get('quarterly'), dict) else {}
    annual = periods.get('annual') if isinstance(periods.get('annual'), dict) else {}
    if flow and len(quarterly) >= 4:
        dated = []
        for period, detail in quarterly.items():
            try:
                dated.append((pd.Timestamp(period).normalize(), detail))
            except (TypeError, ValueError):
                continue
        dated.sort(key=lambda item: item[0], reverse=True)
        latest = dated[:4]
        gaps = [(latest[index][0] - latest[index + 1][0]).days for index in range(3)] if len(latest) == 4 else []
        if len(latest) == 4 and all(50 <= gap <= 140 for gap in gaps):
            return {
                'source': 'SEC EDGAR',
                'basis': 'TTM from four complete quarters',
                'period': f'{latest[-1][0].date()} to {latest[0][0].date()}',
                'facts': [dict(detail) for _, detail in reversed(latest) if isinstance(detail, dict)],
            }
    if flow and annual:
        period = max(annual)
        detail = annual.get(period)
        return {
            'source': 'SEC EDGAR',
            'basis': 'Latest annual filing',
            'period': period,
            'facts': [dict(detail)] if isinstance(detail, dict) else [],
        }
    if not flow:
        instants = {**annual, **quarterly}
        if instants:
            period = max(instants)
            detail = instants.get(period)
            return {
                'source': 'SEC EDGAR',
                'basis': 'Latest reported instant',
                'period': period,
                'facts': [dict(detail)] if isinstance(detail, dict) else [],
            }
    return {
        'source': 'yfinance',
        'basis': 'Yahoo metadata or statement fallback',
        'period': '',
        'facts': [],
    }


def _historical_series(frame: Any, aliases: tuple[str, ...]) -> list[tuple[str, float]]:
    values = _numeric_statement_values(frame, aliases)
    if values is None:
        return []
    points = []
    for column, value in values.items():
        numeric = _safe_float(value)
        if numeric is None:
            continue
        label = str(column)[:4] if str(column) else ''
        if not label:
            continue
        points.append((label, numeric))
    points.reverse()
    return points[-5:]


def _info_value(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _safe_float(info.get(key))
        if value is not None:
            return value
    return None


def _prefer_number(primary: float | None, fallback: float | None) -> float | None:
    """Preserve valid zero values while applying source precedence."""
    return primary if primary is not None else fallback


def _first_text(info: dict[str, Any], *keys: str, fallback: str = '') -> str:
    for key in keys:
        text = str(info.get(key) or '').strip()
        if text:
            return text
    return fallback


def _optional_value(label: str, ticker: str, getter: Any) -> Any:
    try:
        return getter()
    except Exception as exc:
        if is_yahoo_unauthorized_error(exc):
            logger.info('Yahoo refused optional valuation %s for %s.', label, ticker)
        else:
            logger.info('Optional valuation %s fetch failed for %s: %s', label, ticker, exc)
        return None


def _fallback_info_from_history(ticker: str, ticker_obj: Any) -> dict[str, Any]:
    try:
        history = ticker_obj.history(period='5d', interval='1d')
    except Exception:
        return {}
    if history is None or history.empty or 'Close' not in history.columns:
        return {}
    closes = history['Close'].dropna()
    if closes.empty:
        return {}
    info = {
        'symbol': ticker,
        'shortName': ticker,
        'regularMarketPrice': float(closes.iloc[-1]),
        'currentPrice': float(closes.iloc[-1]),
    }
    if len(closes) >= 2:
        info['previousClose'] = float(closes.iloc[-2])
    return info


def _load_info(ticker: str, ticker_obj: Any) -> dict[str, Any]:
    try:
        info = ticker_obj.info
        if not isinstance(info, dict):
            info = {}
    except Exception as exc:
        if is_yahoo_unauthorized_error(exc):
            logger.info('Yahoo refused valuation metadata for %s; using price-history fallback.', ticker)
        else:
            logger.info('Valuation metadata fetch failed for %s: %s', ticker, exc)
        info = {}
    fallback = _fallback_info_from_history(ticker, ticker_obj)
    for key, value in fallback.items():
        if info.get(key) is None:
            info[key] = value
    return info


def _extract_metrics(
    ticker: str,
    info: dict[str, Any],
    financials: Any,
    cashflow: Any,
    balance_sheet: Any,
    quarterly_financials: Any,
    quarterly_cashflow: Any,
    quarterly_balance_sheet: Any,
    price_history: Any,
    *,
    prefer_statements: bool = False,
) -> dict[str, Any]:
    price = _info_value(info, 'currentPrice', 'regularMarketPrice', 'previousClose')
    if price is None and isinstance(price_history, pd.DataFrame) and not price_history.empty and 'Close' in price_history.columns:
        price = _safe_float(price_history['Close'].dropna().iloc[-1])
    market_cap = _info_value(info, 'marketCap')
    reported_revenue = _reported_flow_value(quarterly_financials, financials, ('total revenue', 'revenue'))
    reported_net_income = _reported_flow_value(
        quarterly_financials,
        financials,
        ('net income', 'net income common stockholders'),
    )
    info_revenue = _info_value(info, 'totalRevenue')
    info_net_income = _info_value(info, 'netIncomeToCommon', 'netIncome')
    revenue = _prefer_number(reported_revenue, info_revenue) if prefer_statements else _prefer_number(info_revenue, reported_revenue)
    net_income = _prefer_number(reported_net_income, info_net_income) if prefer_statements else _prefer_number(info_net_income, reported_net_income)
    ebitda = _info_value(info, 'ebitda') or _latest_statement_value((quarterly_financials, financials), ('ebitda', 'normalized ebitda'), flow=True)
    reported_operating_cash_flow = _reported_flow_value(
        quarterly_cashflow,
        cashflow,
        ('operating cash flow', 'total cash from operating activities'),
    )
    info_operating_cash_flow = _info_value(info, 'operatingCashflow')
    operating_cash_flow = (
        _prefer_number(reported_operating_cash_flow, info_operating_cash_flow)
        if prefer_statements
        else _prefer_number(info_operating_cash_flow, reported_operating_cash_flow)
    )
    capex = _reported_flow_value(quarterly_cashflow, cashflow, ('capital expenditure', 'capital expenditures'))
    reported_fcf = _reported_flow_value(quarterly_cashflow, cashflow, ('free cash flow',))
    info_fcf = _info_value(info, 'freeCashflow')
    free_cash_flow = _prefer_number(reported_fcf, info_fcf) if prefer_statements else _prefer_number(info_fcf, reported_fcf)
    if free_cash_flow is None and operating_cash_flow is not None and capex is not None:
        free_cash_flow = operating_cash_flow - abs(capex)
    reported_shares = _latest_statement_value((quarterly_balance_sheet, balance_sheet), ('ordinary shares number', 'share issued', 'common stock shares outstanding'))
    info_shares = _info_value(info, 'sharesOutstanding', 'impliedSharesOutstanding')
    shares = _prefer_number(reported_shares, info_shares) if prefer_statements else _prefer_number(info_shares, reported_shares)
    reported_eps = _reported_flow_value(quarterly_financials, financials, ('diluted eps', 'diluted earnings per share'))
    info_eps = _info_value(info, 'trailingEps', 'currentEps')
    eps = _prefer_number(reported_eps, info_eps) if prefer_statements else _prefer_number(info_eps, reported_eps)
    if eps is None and net_income is not None and shares:
        eps = net_income / shares
    fcf_per_share = free_cash_flow / shares if free_cash_flow is not None and shares else None
    reported_cash = _latest_statement_value((quarterly_balance_sheet, balance_sheet), ('cash and cash equivalents', 'cash cash equivalents and short term investments', 'cash equivalents and short term investments'))
    reported_debt = _latest_statement_value((quarterly_balance_sheet, balance_sheet), ('total debt', 'long term debt and capital lease obligation', 'long term debt'))
    info_cash = _info_value(info, 'totalCash')
    info_debt = _info_value(info, 'totalDebt')
    cash = _prefer_number(reported_cash, info_cash) if prefer_statements else _prefer_number(info_cash, reported_cash)
    debt = _prefer_number(reported_debt, info_debt) if prefer_statements else _prefer_number(info_debt, reported_debt)
    enterprise_value = _info_value(info, 'enterpriseValue')
    if enterprise_value is None and market_cap is not None:
        enterprise_value = market_cap + (debt or 0.0) - (cash or 0.0)
    basis_value = fcf_per_share if fcf_per_share is not None and fcf_per_share > 0 else eps
    basis_type = 'FCF' if fcf_per_share is not None and fcf_per_share > 0 else 'EPS'
    pe = price / eps if price is not None and eps and eps > 0 else None
    earnings_yield = eps / price * 100.0 if price and eps and eps > 0 else None
    fcf_yield = free_cash_flow / market_cap * 100.0 if free_cash_flow is not None and market_cap else None
    ps = market_cap / revenue if market_cap and revenue and revenue > 0 else None
    ev_ebitda = enterprise_value / ebitda if enterprise_value and ebitda and ebitda > 0 else None
    net_margin = net_income / revenue * 100.0 if net_income is not None and revenue else None
    return {
        'ticker': ticker,
        'company_name': _first_text(info, 'longName', 'shortName', fallback=ticker),
        'sector': _first_text(info, 'sector', fallback='N/A'),
        'industry': _first_text(info, 'industry', fallback='N/A'),
        'price': price,
        'previous_close': _info_value(info, 'previousClose'),
        'market_cap': market_cap,
        'enterprise_value': enterprise_value,
        'revenue': revenue,
        'net_income': net_income,
        'ebitda': ebitda,
        'operating_cash_flow': operating_cash_flow,
        'free_cash_flow': free_cash_flow,
        'shares': shares,
        'eps': eps,
        'fcf_per_share': fcf_per_share,
        'basis_type': basis_type,
        'basis_value': basis_value,
        'cash': cash,
        'debt': debt,
        'net_debt': (debt or 0.0) - (cash or 0.0) if debt is not None or cash is not None else None,
        'pe': pe,
        'forward_pe': _info_value(info, 'forwardPE'),
        'ps': ps,
        'pb': _info_value(info, 'priceToBook'),
        'ev_ebitda': ev_ebitda,
        'fcf_yield': fcf_yield,
        'earnings_yield': earnings_yield,
        'peg': _info_value(info, 'pegRatio', 'trailingPegRatio'),
        'dividend_yield': (_info_value(info, 'dividendYield') or 0.0) * 100.0 if _info_value(info, 'dividendYield') is not None else None,
        'net_margin': net_margin,
        'revenue_growth': (_info_value(info, 'revenueGrowth') * 100.0) if _info_value(info, 'revenueGrowth') is not None else None,
        'beta': _info_value(info, 'beta'),
    }


def _build_trends(financials: Any, cashflow: Any, metrics: dict[str, Any]) -> dict[str, Any]:
    revenue_points = _historical_series(financials, ('total revenue', 'revenue'))
    net_income_points = _historical_series(financials, ('net income', 'net income common stockholders'))
    operating_cash_points = _historical_series(cashflow, ('operating cash flow', 'total cash from operating activities'))
    capex_points = _historical_series(cashflow, ('capital expenditure', 'capital expenditures'))
    diluted_share_points = _historical_series(
        financials,
        ('diluted average shares', 'diluted average shares number', 'diluted weighted average shares'),
    )
    fcf_map = {}
    for label, value in operating_cash_points:
        fcf_map[label] = fcf_map.get(label, 0.0) + value
    for label, value in capex_points:
        fcf_map[label] = fcf_map.get(label, 0.0) - abs(value)
    labels = [label for label, _ in revenue_points] or [label for label, _ in net_income_points]
    shares = metrics.get('shares') or 0.0
    diluted_shares = {label: value for label, value in diluted_share_points if value > 0}
    used_current_share_fallback = False

    def _per_share(points: list[tuple[str, float]]) -> list[float | None]:
        nonlocal used_current_share_fallback
        point_map = dict(points)
        values: list[float | None] = []
        for label in labels:
            value = point_map.get(label)
            period_shares = diluted_shares.get(label)
            if value is None:
                values.append(None)
            elif period_shares:
                values.append(value / period_shares)
            elif shares:
                used_current_share_fallback = True
                values.append(value / shares)
            else:
                values.append(None)
        return values

    eps_series = _per_share(net_income_points)
    fcf_points = [(label, fcf_map.get(label)) for label in labels if fcf_map.get(label) is not None]
    fcf_per_share_series = _per_share(fcf_points)
    basis_series = fcf_per_share_series if metrics.get('basis_type') == 'FCF' else eps_series
    return {
        'labels': labels,
        'revenue': [value for _, value in revenue_points],
        'eps': eps_series,
        'fcf': [fcf_map.get(label) for label in labels],
        'fcf_per_share': fcf_per_share_series,
        'per_share_approximate': used_current_share_fallback,
        'per_share_source': 'Period diluted average shares' if diluted_shares and not used_current_share_fallback else 'Current shares fallback (approximate)',
        'comparable_history_points': sum(1 for value in basis_series if value is not None and value > 0),
    }


def _peer_text(value: Any) -> str:
    text = str(value or '').replace('&', ' and ').replace('/', ' ').replace('-', ' ')
    return ' '.join(text.lower().split())


def _peer_key(value: Any) -> str:
    return ''.join(char for char in _peer_text(value) if char.isalnum())


def _peer_matches(text: str, keywords: tuple[str, ...]) -> bool:
    text_key = _peer_key(text)
    for keyword in keywords:
        keyword_text = _peer_text(keyword)
        keyword_key = _peer_key(keyword_text)
        if keyword_text and keyword_text in text:
            return True
        if keyword_key and keyword_key in text_key:
            return True
    return False


def _peer_add_candidates(scores: dict[str, float], symbols: tuple[str, ...] | list[str], source_score: float, *, current_symbol: str) -> None:
    for raw_symbol in symbols:
        peer_symbol = str(raw_symbol or '').upper().strip()
        if not peer_symbol or peer_symbol == current_symbol:
            continue
        scores[peer_symbol] = max(scores.get(peer_symbol, 0.0), source_score)


def _normalize_peer_symbols(values: Any, *, current_symbol: str='') -> list[str]:
    symbols = []
    if not isinstance(values, list | tuple):
        return symbols
    current_symbol = str(current_symbol or '').upper().strip()
    for raw_symbol in values:
        peer_symbol = str(raw_symbol or '').upper().strip()
        if not peer_symbol or peer_symbol == current_symbol or peer_symbol in symbols:
            continue
        symbols.append(peer_symbol)
    return symbols


def _peer_sector_name(sector: Any) -> str:
    key = _peer_key(sector)
    if key in SECTOR_ALIASES:
        return SECTOR_ALIASES[key]
    for name in SECTOR_DATA:
        name_key = _peer_key(name)
        if key and (key == name_key or key in name_key or name_key in key):
            return name
    return ''


def _peer_candidate_scores(symbol: str, info: dict[str, Any]) -> dict[str, float]:
    current_symbol = str(symbol or '').upper().strip()
    industry = _peer_text(info.get('industry'))
    sector_name = _peer_sector_name(info.get('sector'))
    scores: dict[str, float] = {}
    matched_industry = False
    for keywords, symbols in INDUSTRY_PEER_GROUPS:
        if current_symbol in symbols or _peer_matches(industry, keywords):
            matched_industry = True
            _peer_add_candidates(scores, symbols, 120.0, current_symbol=current_symbol)
    if sector_name:
        _peer_add_candidates(scores, SECTOR_DATA.get(sector_name, []), 70.0 if matched_industry else 90.0, current_symbol=current_symbol)
    _peer_add_candidates(scores, DEFAULT_PEERS, 10.0, current_symbol=current_symbol)
    return scores


def _peer_candidate_symbols(symbol: str, info: dict[str, Any]) -> list[str]:
    scores = _peer_candidate_scores(symbol, info)
    ordered = sorted(scores, key=lambda peer: -scores[peer])
    return ordered[:PEER_CANDIDATE_LIMIT]


def _peer_market_cap_score(anchor_cap: float | None, peer_cap: float | None) -> float:
    if anchor_cap is None or peer_cap is None or anchor_cap <= 0 or peer_cap <= 0:
        return 0.0
    try:
        distance = abs(math.log(peer_cap / anchor_cap))
    except (ValueError, ZeroDivisionError):
        return 0.0
    return max(0.0, 30.0 - distance * 15.0)


def _peer_score(symbol: str, info: dict[str, Any], peer_symbol: str, peer_info: dict[str, Any], source_score: float) -> float:
    score = float(source_score)
    anchor_industry = _peer_key(info.get('industry'))
    peer_industry = _peer_key(peer_info.get('industry'))
    if anchor_industry and peer_industry:
        if anchor_industry == peer_industry:
            score += 60.0
        elif anchor_industry in peer_industry or peer_industry in anchor_industry:
            score += 25.0
    if _peer_sector_name(info.get('sector')) and _peer_sector_name(info.get('sector')) == _peer_sector_name(peer_info.get('sector')):
        score += 35.0
    quote_type = str(peer_info.get('quoteType') or '').upper().strip()
    if quote_type and quote_type != 'EQUITY':
        score -= 40.0
    elif quote_type == 'EQUITY':
        score += 5.0
    score += _peer_market_cap_score(_info_value(info, 'marketCap'), _info_value(peer_info, 'marketCap'))
    if peer_symbol == symbol:
        score -= 1000.0
    return score


def _peer_symbols(symbol: str, info: dict[str, Any], peer_infos: dict[str, dict[str, Any]] | None = None, custom_peers: Any=None, row_limit: int | None=None) -> list[str]:
    current_symbol = str(symbol or '').upper().strip()
    custom_symbols = _normalize_peer_symbols(custom_peers, current_symbol=current_symbol)
    if row_limit is None:
        row_limit = PEER_ROW_LIMIT if not custom_symbols else max(PEER_ROW_LIMIT, 1 + len(custom_symbols) + max(0, PEER_ROW_LIMIT - 1))
    row_limit = min(max(int(row_limit), PEER_ROW_LIMIT), PEER_CUSTOM_ROW_LIMIT)
    source_scores = _peer_candidate_scores(current_symbol, info)
    peer_infos = peer_infos or {}
    ordered = sorted(
        source_scores,
        key=lambda peer: -_peer_score(current_symbol, info, peer, peer_infos.get(peer, {}), source_scores[peer]),
    )
    symbols = [current_symbol] if current_symbol else []
    for peer in custom_symbols:
        if peer and peer not in symbols:
            symbols.append(peer)
        if len(symbols) >= row_limit:
            return symbols
    for peer in ordered:
        if peer and peer not in symbols:
            symbols.append(peer)
        if len(symbols) >= row_limit:
            break
    return symbols


def _peer_info_has_usable_data(info: dict[str, Any]) -> bool:
    if not isinstance(info, dict) or not info:
        return False
    return any(info.get(key) is not None for key in ('shortName', 'longName', 'currentPrice', 'regularMarketPrice', 'marketCap'))


def _peer_row(peer: str, peer_info: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        'ticker': peer,
        'company': _first_text(peer_info, 'shortName', 'longName', fallback=peer),
        'source': source,
        'market_cap': _info_value(peer_info, 'marketCap'),
        'revenue_growth': (_info_value(peer_info, 'revenueGrowth') * 100.0) if _info_value(peer_info, 'revenueGrowth') is not None else None,
        'net_margin': (_info_value(peer_info, 'profitMargins') * 100.0) if _info_value(peer_info, 'profitMargins') is not None else None,
        'pe': _info_value(peer_info, 'trailingPE'),
        'forward_pe': _info_value(peer_info, 'forwardPE'),
        'ev_ebitda': _info_value(peer_info, 'enterpriseToEbitda'),
        'fcf_yield': (_info_value(peer_info, 'freeCashflow') / _info_value(peer_info, 'marketCap') * 100.0) if _info_value(peer_info, 'freeCashflow') is not None and _info_value(peer_info, 'marketCap') else None,
    }


def _build_peer_rows(symbol: str, info: dict[str, Any], custom_peers: Any=None) -> tuple[list[dict[str, Any]], list[str]]:
    current_symbol = str(symbol or '').upper().strip()
    custom_symbols = _normalize_peer_symbols(custom_peers, current_symbol=current_symbol)
    peer_infos = {str(symbol or '').upper().strip(): info}
    peer_warnings = []
    for peer in custom_symbols:
        ticker_obj = yf.Ticker(peer)
        peer_info = _load_info(peer, ticker_obj)
        if _peer_info_has_usable_data(peer_info):
            peer_infos[peer] = peer_info
        else:
            peer_warnings.append(f'{peer} returned no usable peer data.')
    for peer in _peer_candidate_symbols(symbol, info):
        if peer in peer_infos:
            continue
        ticker_obj = yf.Ticker(peer)
        peer_infos[peer] = _load_info(peer, ticker_obj)
    rows = []
    usable_custom_symbols = [peer for peer in custom_symbols if peer in peer_infos]
    for peer in _peer_symbols(symbol, info, peer_infos, usable_custom_symbols):
        peer_info = peer_infos.get(peer, {})
        source = 'Loaded' if peer == current_symbol else 'Custom' if peer in usable_custom_symbols else 'Auto'
        rows.append(_peer_row(peer, peer_info, source))
    return rows, peer_warnings


def fetch_company_analysis_payload(ticker: Any, custom_peers: Any=None, *, include_peers: bool=True) -> dict[str, Any]:
    """Fetch the reusable company-analysis payload used by Valuation and teaching tools."""
    symbol = str(ticker or '').upper().strip()
    if not symbol:
        raise ValueError('Enter a ticker to load valuation data.')
    normalized_custom_peers = _normalize_peer_symbols(custom_peers, current_symbol=symbol)
    ticker_obj = yf.Ticker(symbol)
    info = _load_info(symbol, ticker_obj)
    price_history = _optional_value('price history', symbol, lambda: ticker_obj.history(period='5y', interval='1mo'))
    financials = _optional_value('financials', symbol, lambda: ticker_obj.financials)
    cashflow = _optional_value('cashflow', symbol, lambda: ticker_obj.cashflow)
    balance_sheet = _optional_value('balance sheet', symbol, lambda: ticker_obj.balance_sheet)
    quarterly_financials = _optional_value('quarterly financials', symbol, lambda: ticker_obj.quarterly_financials)
    quarterly_cashflow = _optional_value('quarterly cashflow', symbol, lambda: ticker_obj.quarterly_cashflow)
    quarterly_balance_sheet = _optional_value('quarterly balance sheet', symbol, lambda: ticker_obj.quarterly_balance_sheet)
    try:
        sec_bundle = fetch_company_bundle(symbol)
    except Exception as exc:
        logger.info('Valuation SEC fetch failed for %s: %s', symbol, exc)
        sec_bundle = {
            'available': False,
            'statements_available': False,
            'ticker': symbol,
            'filings': [],
            'provenance': {},
            'warnings': [f'SEC: {exc}'],
        }
    yahoo_metrics = _extract_metrics(
        symbol,
        info,
        financials,
        cashflow,
        balance_sheet,
        quarterly_financials,
        quarterly_cashflow,
        quarterly_balance_sheet,
        price_history,
    )
    sec_backed = bool(sec_bundle.get('statements_available'))
    metrics = yahoo_metrics
    if sec_backed:
        fallback_info = dict(info)
        for info_key, metric_key in (
            ('totalRevenue', 'revenue'),
            ('netIncome', 'net_income'),
            ('ebitda', 'ebitda'),
            ('operatingCashflow', 'operating_cash_flow'),
            ('freeCashflow', 'free_cash_flow'),
            ('sharesOutstanding', 'shares'),
            ('totalCash', 'cash'),
            ('totalDebt', 'debt'),
            ('trailingEps', 'eps'),
        ):
            if fallback_info.get(info_key) is None and yahoo_metrics.get(metric_key) is not None:
                fallback_info[info_key] = yahoo_metrics[metric_key]
        sec_frames = sec_bundle.get('frames') if isinstance(sec_bundle.get('frames'), dict) else {}
        metrics = _extract_metrics(
            symbol,
            fallback_info,
            sec_frames.get('financials'),
            sec_frames.get('cashflow'),
            sec_frames.get('balance_sheet'),
            sec_frames.get('quarterly_financials'),
            sec_frames.get('quarterly_cashflow'),
            sec_frames.get('quarterly_balance_sheet'),
            price_history,
            prefer_statements=True,
        )
        merged = merge_sec_frames(
            {
                'financials': financials,
                'cashflow': cashflow,
                'balance_sheet': balance_sheet,
                'quarterly_financials': quarterly_financials,
                'quarterly_cashflow': quarterly_cashflow,
                'quarterly_balance_sheet': quarterly_balance_sheet,
            },
            sec_bundle,
        )
        financials = merged.get('financials')
        cashflow = merged.get('cashflow')
        balance_sheet = merged.get('balance_sheet')
        quarterly_financials = merged.get('quarterly_financials')
        quarterly_cashflow = merged.get('quarterly_cashflow')
        quarterly_balance_sheet = merged.get('quarterly_balance_sheet')
    if metrics.get('price') is None:
        raise ValueError(f"No quote data found for '{symbol}'. Check the ticker symbol.")
    peer_rows, peer_warnings = _build_peer_rows(symbol, info, normalized_custom_peers) if include_peers else ([], [])
    trends = _build_trends(financials, cashflow, metrics)
    suggestions = derive_valuation_suggestions(metrics, trends, metrics.get('basis_type'))
    suggested_assumptions = {
        key: detail.get('value')
        for key, detail in suggestions.get('fields', {}).items()
        if isinstance(detail, dict) and detail.get('value') is not None
    }
    sec_payload = {key: value for key, value in sec_bundle.items() if key != 'frames'}
    valuation_provenance = {
        metric: _selected_sec_provenance(sec_bundle, row, flow=flow) if sec_backed else {
            'source': 'yfinance',
            'basis': 'Yahoo metadata or statement fallback',
            'period': '',
            'facts': [],
        }
        for metric, row, flow in (
            ('Revenue', 'Total Revenue', True),
            ('Net income', 'Net Income', True),
            ('Operating cash flow', 'Operating Cash Flow', True),
            ('Free cash flow', 'Free Cash Flow', True),
            ('Cash', 'Cash Cash Equivalents And Short Term Investments', False),
            ('Debt', 'Total Debt', False),
            ('Shares', 'Common Stock Shares Outstanding', False),
            ('Diluted EPS', 'Diluted EPS', True),
        )
    }
    return {
        'ticker': symbol,
        'info': info,
        'metrics': metrics,
        'price_history': price_history,
        'financials': financials,
        'cashflow': cashflow,
        'balance_sheet': balance_sheet,
        'quarterly_financials': quarterly_financials,
        'quarterly_cashflow': quarterly_cashflow,
        'quarterly_balance_sheet': quarterly_balance_sheet,
        'trends': trends,
        'valuation_suggestions': suggestions,
        'assumption_suggestions': suggestions,
        'suggested_assumptions': suggested_assumptions,
        'peer_rows': peer_rows,
        'peer_warnings': peer_warnings,
        'sec': sec_payload,
        'statement_sources': {
            'primary': 'SEC EDGAR' if sec_backed else 'yfinance',
            'fallback': 'yfinance',
        },
        'valuation_provenance': valuation_provenance,
        'av_used': False,
        'fetched_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'sources': {
            'quote': 'yfinance quote/history',
            'statements': 'SEC EDGAR XBRL with yfinance fallback' if sec_backed else 'yfinance financial statements',
            'computed': 'Computed from quote, statements, and assumptions',
            'suggestions': (
                'SEC-backed consecutive annual statements and Yahoo quote metadata; '
                'required return is a transparent heuristic'
                if sec_backed
                else 'Consecutive annual statements and quote metadata; required return is a transparent heuristic'
            ),
        },
    }


class ValuationWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, ticker: Any, custom_peers: Any=None) -> None:
        super().__init__()
        self.ticker = str(ticker or '').upper().strip()
        self.custom_peers = _normalize_peer_symbols(custom_peers, current_symbol=self.ticker)

    def run(self) -> None:
        try:
            self.finished.emit(fetch_company_analysis_payload(self.ticker, self.custom_peers, include_peers=True))
        except ValueError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f'Error fetching valuation data: {exc}')
