from __future__ import annotations

from typing import Any

from ..constants import SECTOR_DATA
from ..dependencies import *


DEFAULT_VALUATION_ASSUMPTIONS: dict[str, float | int | str] = {
    'basis_type': 'FCF',
    'basis_value': 0.0,
    'growth_1_5': 20.0,
    'growth_6_10': 8.0,
    'discount_rate': 9.0,
    'terminal_growth': 3.0,
    'exit_multiple': 20.0,
    'projection_years': 10,
    'margin_of_safety': 15.0,
}


PEER_ROW_LIMIT = 5
PEER_CANDIDATE_LIMIT = 16
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


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    numeric = _safe_float(value, default)
    if numeric is None:
        numeric = default
    return min(max(float(numeric), minimum), maximum)


def normalize_valuation_assumptions(values: Any) -> dict[str, Any]:
    """Return supported valuation assumptions with stable bounds."""
    saved = values if isinstance(values, dict) else {}
    basis_type = str(saved.get('basis_type', DEFAULT_VALUATION_ASSUMPTIONS['basis_type']) or 'FCF').upper().strip()
    if basis_type not in {'FCF', 'EPS'}:
        basis_type = 'FCF'
    years_raw = saved.get('projection_years', DEFAULT_VALUATION_ASSUMPTIONS['projection_years'])
    try:
        years = int(years_raw)
    except (TypeError, ValueError):
        years = int(DEFAULT_VALUATION_ASSUMPTIONS['projection_years'])
    years = min(max(years, 1), 15)
    return {
        'basis_type': basis_type,
        'basis_value': _bounded_float(saved.get('basis_value', DEFAULT_VALUATION_ASSUMPTIONS['basis_value']), 0.0, 0.0, 100000.0),
        'growth_1_5': _bounded_float(saved.get('growth_1_5', DEFAULT_VALUATION_ASSUMPTIONS['growth_1_5']), 20.0, -50.0, 100.0),
        'growth_6_10': _bounded_float(saved.get('growth_6_10', DEFAULT_VALUATION_ASSUMPTIONS['growth_6_10']), 8.0, -50.0, 100.0),
        'discount_rate': _bounded_float(saved.get('discount_rate', DEFAULT_VALUATION_ASSUMPTIONS['discount_rate']), 9.0, 0.1, 50.0),
        'terminal_growth': _bounded_float(saved.get('terminal_growth', DEFAULT_VALUATION_ASSUMPTIONS['terminal_growth']), 3.0, -10.0, 20.0),
        'exit_multiple': _bounded_float(saved.get('exit_multiple', DEFAULT_VALUATION_ASSUMPTIONS['exit_multiple']), 20.0, 1.0, 100.0),
        'projection_years': years,
        'margin_of_safety': _bounded_float(saved.get('margin_of_safety', DEFAULT_VALUATION_ASSUMPTIONS['margin_of_safety']), 15.0, 0.0, 90.0),
    }


def calculate_fair_value_per_share(assumptions: Any) -> float | None:
    """Discount projected per-share owner earnings and terminal value."""
    values = normalize_valuation_assumptions(assumptions)
    basis = _safe_float(values.get('basis_value'))
    if basis is None or basis <= 0:
        return None
    discount = max(float(values['discount_rate']) / 100.0, 0.001)
    growth_1_5 = float(values['growth_1_5']) / 100.0
    growth_6_10 = float(values['growth_6_10']) / 100.0
    terminal_growth = float(values['terminal_growth']) / 100.0
    exit_multiple = max(float(values['exit_multiple']), 0.01)
    years = int(values['projection_years'])
    current = float(basis)
    present_value = 0.0
    for year in range(1, years + 1):
        growth = growth_1_5 if year <= 5 else growth_6_10
        current *= 1.0 + growth
        present_value += current / ((1.0 + discount) ** year)
    terminal_cash_flow = current * (1.0 + terminal_growth)
    terminal_value = terminal_cash_flow * exit_multiple
    present_value += terminal_value / ((1.0 + discount) ** years)
    return max(present_value, 0.0)


def calculate_valuation_scenarios(price: Any, assumptions: Any) -> dict[str, Any]:
    """Calculate bear/base/bull fair values and verdict metadata."""
    base = normalize_valuation_assumptions(assumptions)
    bear = {
        **base,
        'growth_1_5': float(base['growth_1_5']) * 0.5,
        'growth_6_10': float(base['growth_6_10']) * 0.5,
        'discount_rate': float(base['discount_rate']) + 1.0,
        'exit_multiple': float(base['exit_multiple']) * 0.8,
    }
    bull = {
        **base,
        'growth_1_5': float(base['growth_1_5']) * 1.5,
        'growth_6_10': float(base['growth_6_10']) * 1.5,
        'discount_rate': max(float(base['discount_rate']) - 1.0, 0.1),
        'exit_multiple': float(base['exit_multiple']) * 1.2,
    }
    scenarios = []
    for name, scenario_values in (
        ('Bear Case', bear),
        ('Base Case', base),
        ('Bull Case', bull),
    ):
        fair_value = calculate_fair_value_per_share(scenario_values)
        price_value = _safe_float(price)
        upside = None
        if fair_value is not None and price_value is not None and price_value > 0:
            upside = (fair_value / price_value - 1.0) * 100.0
        scenarios.append({
            'name': name,
            'fair_value': fair_value,
            'upside_pct': upside,
            'assumptions': normalize_valuation_assumptions(scenario_values),
        })
    base_value = scenarios[1]['fair_value']
    margin = float(base['margin_of_safety']) / 100.0
    buy_below = base_value * (1.0 - margin) if base_value is not None else None
    trim_above = base_value * (1.0 + margin) if base_value is not None else None
    price_value = _safe_float(price)
    if price_value is None or price_value <= 0 or base_value is None:
        verdict = 'Too uncertain'
    elif buy_below is not None and price_value < buy_below:
        verdict = 'Undervalued'
    elif trim_above is not None and price_value > trim_above:
        verdict = 'Overvalued'
    else:
        verdict = 'Fairly valued'
    return {
        'assumptions': base,
        'scenarios': scenarios,
        'base_fair_value': base_value,
        'buy_below': buy_below,
        'trim_above': trim_above,
        'verdict': verdict,
    }


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
        if flow and frame_index == 0 and len(values) >= 4:
            return _safe_float(values.iloc[:4].sum())
        return _safe_float(values.iloc[0])
    return None


def _historical_series(frame: Any, aliases: tuple[str, ...], *, invert_capex: bool = False) -> list[tuple[str, float]]:
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
        points.append((label, -numeric if invert_capex else numeric))
    points.reverse()
    return points[-5:]


def _info_value(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _safe_float(info.get(key))
        if value is not None:
            return value
    return None


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


def _extract_metrics(ticker: str, info: dict[str, Any], financials: Any, cashflow: Any, balance_sheet: Any, quarterly_financials: Any, quarterly_cashflow: Any, quarterly_balance_sheet: Any, price_history: Any) -> dict[str, Any]:
    price = _info_value(info, 'currentPrice', 'regularMarketPrice', 'previousClose')
    if price is None and isinstance(price_history, pd.DataFrame) and not price_history.empty and 'Close' in price_history.columns:
        price = _safe_float(price_history['Close'].dropna().iloc[-1])
    market_cap = _info_value(info, 'marketCap')
    revenue = _info_value(info, 'totalRevenue') or _latest_statement_value((quarterly_financials, financials), ('total revenue', 'revenue'), flow=True)
    net_income = _info_value(info, 'netIncomeToCommon', 'netIncome') or _latest_statement_value((quarterly_financials, financials), ('net income', 'net income common stockholders'), flow=True)
    ebitda = _info_value(info, 'ebitda') or _latest_statement_value((quarterly_financials, financials), ('ebitda', 'normalized ebitda'), flow=True)
    operating_cash_flow = _info_value(info, 'operatingCashflow') or _latest_statement_value((quarterly_cashflow, cashflow), ('operating cash flow', 'total cash from operating activities'), flow=True)
    capex = _latest_statement_value((quarterly_cashflow, cashflow), ('capital expenditure', 'capital expenditures'), flow=True)
    free_cash_flow = _info_value(info, 'freeCashflow')
    if free_cash_flow is None and operating_cash_flow is not None and capex is not None:
        free_cash_flow = operating_cash_flow + capex if capex < 0 else operating_cash_flow - capex
    shares = _info_value(info, 'sharesOutstanding', 'impliedSharesOutstanding') or _latest_statement_value((quarterly_balance_sheet, balance_sheet), ('ordinary shares number', 'share issued', 'common stock shares outstanding'))
    eps = _info_value(info, 'trailingEps', 'currentEps')
    if eps is None and net_income is not None and shares:
        eps = net_income / shares
    fcf_per_share = free_cash_flow / shares if free_cash_flow is not None and shares else None
    cash = _info_value(info, 'totalCash') or _latest_statement_value((quarterly_balance_sheet, balance_sheet), ('cash and cash equivalents', 'cash cash equivalents and short term investments', 'cash equivalents and short term investments'))
    debt = _info_value(info, 'totalDebt') or _latest_statement_value((quarterly_balance_sheet, balance_sheet), ('total debt', 'long term debt and capital lease obligation', 'long term debt'))
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


def _build_trends(financials: Any, cashflow: Any, metrics: dict[str, Any]) -> dict[str, list[Any]]:
    revenue_points = _historical_series(financials, ('total revenue', 'revenue'))
    net_income_points = _historical_series(financials, ('net income', 'net income common stockholders'))
    operating_cash_points = _historical_series(cashflow, ('operating cash flow', 'total cash from operating activities'))
    capex_points = _historical_series(cashflow, ('capital expenditure', 'capital expenditures'), invert_capex=True)
    fcf_map = {}
    for label, value in operating_cash_points:
        fcf_map[label] = fcf_map.get(label, 0.0) + value
    for label, value in capex_points:
        fcf_map[label] = fcf_map.get(label, 0.0) - value
    labels = [label for label, _ in revenue_points] or [label for label, _ in net_income_points]
    shares = metrics.get('shares') or 0.0
    return {
        'labels': labels,
        'revenue': [value for _, value in revenue_points],
        'eps': [(value / shares) if shares else None for _, value in net_income_points],
        'fcf': [fcf_map.get(label) for label in labels],
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


def _peer_symbols(symbol: str, info: dict[str, Any], peer_infos: dict[str, dict[str, Any]] | None = None) -> list[str]:
    current_symbol = str(symbol or '').upper().strip()
    source_scores = _peer_candidate_scores(current_symbol, info)
    peer_infos = peer_infos or {}
    ordered = sorted(
        source_scores,
        key=lambda peer: -_peer_score(current_symbol, info, peer, peer_infos.get(peer, {}), source_scores[peer]),
    )
    symbols = [current_symbol] if current_symbol else []
    for peer in ordered:
        if peer and peer not in symbols:
            symbols.append(peer)
        if len(symbols) >= PEER_ROW_LIMIT:
            break
    return symbols


def _build_peer_rows(symbol: str, info: dict[str, Any]) -> list[dict[str, Any]]:
    peer_infos = {str(symbol or '').upper().strip(): info}
    for peer in _peer_candidate_symbols(symbol, info):
        ticker_obj = yf.Ticker(peer)
        peer_infos[peer] = _load_info(peer, ticker_obj)
    rows = []
    for peer in _peer_symbols(symbol, info, peer_infos):
        peer_info = peer_infos.get(peer, {})
        rows.append({
            'ticker': peer,
            'company': _first_text(peer_info, 'shortName', 'longName', fallback=peer),
            'market_cap': _info_value(peer_info, 'marketCap'),
            'revenue_growth': (_info_value(peer_info, 'revenueGrowth') * 100.0) if _info_value(peer_info, 'revenueGrowth') is not None else None,
            'net_margin': (_info_value(peer_info, 'profitMargins') * 100.0) if _info_value(peer_info, 'profitMargins') is not None else None,
            'pe': _info_value(peer_info, 'trailingPE'),
            'forward_pe': _info_value(peer_info, 'forwardPE'),
            'ev_ebitda': _info_value(peer_info, 'enterpriseToEbitda'),
            'fcf_yield': (_info_value(peer_info, 'freeCashflow') / _info_value(peer_info, 'marketCap') * 100.0) if _info_value(peer_info, 'freeCashflow') is not None and _info_value(peer_info, 'marketCap') else None,
        })
    return rows


class ValuationWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, ticker: Any) -> None:
        super().__init__()
        self.ticker = str(ticker or '').upper().strip()

    def run(self) -> None:
        try:
            if not self.ticker:
                self.error.emit('Enter a ticker to load valuation data.')
                return
            ticker_obj = yf.Ticker(self.ticker)
            info = _load_info(self.ticker, ticker_obj)
            price_history = _optional_value('price history', self.ticker, lambda: ticker_obj.history(period='5y', interval='1mo'))
            financials = _optional_value('financials', self.ticker, lambda: ticker_obj.financials)
            cashflow = _optional_value('cashflow', self.ticker, lambda: ticker_obj.cashflow)
            balance_sheet = _optional_value('balance sheet', self.ticker, lambda: ticker_obj.balance_sheet)
            quarterly_financials = _optional_value('quarterly financials', self.ticker, lambda: ticker_obj.quarterly_financials)
            quarterly_cashflow = _optional_value('quarterly cashflow', self.ticker, lambda: ticker_obj.quarterly_cashflow)
            quarterly_balance_sheet = _optional_value('quarterly balance sheet', self.ticker, lambda: ticker_obj.quarterly_balance_sheet)
            metrics = _extract_metrics(
                self.ticker,
                info,
                financials,
                cashflow,
                balance_sheet,
                quarterly_financials,
                quarterly_cashflow,
                quarterly_balance_sheet,
                price_history,
            )
            if metrics.get('price') is None:
                self.error.emit(f"No quote data found for '{self.ticker}'. Check the ticker symbol.")
                return
            peer_rows = _build_peer_rows(self.ticker, info)
            self.finished.emit({
                'ticker': self.ticker,
                'info': info,
                'metrics': metrics,
                'price_history': price_history,
                'financials': financials,
                'cashflow': cashflow,
                'balance_sheet': balance_sheet,
                'quarterly_financials': quarterly_financials,
                'quarterly_cashflow': quarterly_cashflow,
                'quarterly_balance_sheet': quarterly_balance_sheet,
                'trends': _build_trends(financials, cashflow, metrics),
                'peer_rows': peer_rows,
                'fetched_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                'sources': {
                    'quote': 'yfinance quote/history',
                    'statements': 'yfinance financial statements',
                    'computed': 'Computed from quote, statements, and assumptions',
                },
            })
        except Exception as exc:
            self.error.emit(f'Error fetching valuation data: {exc}')
