from __future__ import annotations
from typing import Any
from .dependencies import *
from .paths import legacy_documents_user_data_path, user_data_path

DEFAULT_CHART_SLOTS = ['AAPL', 'TSLA', 'NVDA']
USER_DATA_BACKUP_VERSION = 3
USER_DATA_FILE = user_data_path('user_data.json')
LEGACY_USER_DATA_FILE = legacy_documents_user_data_path('user_data.json')
DEFAULT_CHART_PAGE_SETTINGS = {'symbol': 'SPY', 'timeframe_label': '1 Day', 'watchlist': [], 'indicators': ['Volume', '200 MA'], 'auto': True}
DEFAULT_DASHBOARD_CHART_SETTINGS = {'symbol': 'SPY', 'timeframe_label': '1 Day', 'indicators': ['Volume', '200 MA'], 'auto': True, 'splitter_sizes': [5, 2], 'main_splitter_sizes': [3, 5]}
DEFAULT_THEME_SETTINGS = {'selected_theme': 'trading_dark'}
DEFAULT_OPTIONS_CHAIN_SETTINGS = {'default_risk_free_rate': 0.04}
MAX_PORTFOLIOS = 3
MULTI_PORTFOLIO_VERSION = 2
PORTFOLIO_IDS = [f'portfolio_{index}' for index in range(1, MAX_PORTFOLIOS + 1)]
DEFAULT_MAIN_PORTFOLIO_ID = PORTFOLIO_IDS[0]
DEFAULT_PORTFOLIO_NAMES = {portfolio_id: f'Portfolio {index}' for index, portfolio_id in enumerate(PORTFOLIO_IDS, start=1)}
SUPPORTED_THEME_IDS = (DEFAULT_THEME_SETTINGS['selected_theme'],)


def _read_json(path: Any, default: Any) -> Any:
    """Read JSON from disk, returning a fallback on failure."""
    try:
        with Path(path).open() as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: Any, data: Any, *, indent: Any=None) -> None:
    """Write JSON data to disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(f'{target.suffix}.tmp')
    with temp_path.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent)
    temp_path.replace(target)


def _portfolio_payload_with_chart_slots(data: Any, chart_slots: Any=None) -> Any:
    """Normalize saved portfolio payload into the current on-disk shape."""
    slots = list(chart_slots) if chart_slots else list(DEFAULT_CHART_SLOTS)
    if isinstance(data, dict):
        portfolio = data.get('portfolio', [])
        saved_slots = data.get('chart_slots')
        return {'portfolio': portfolio, 'chart_slots': list(saved_slots) if saved_slots else slots}
    if isinstance(data, list):
        return {'portfolio': data, 'chart_slots': slots}
    return {'portfolio': [], 'chart_slots': slots}


def _normalize_portfolio_id(value: Any) -> Any:
    """Normalize a requested portfolio id into a known fixed slot id."""
    text = str(value or '').strip()
    return text if text in PORTFOLIO_IDS else DEFAULT_MAIN_PORTFOLIO_ID


def _normalize_theme_setting(value: Any) -> Any:
    """Clamp persisted theme ids to the currently supported user-selectable set."""
    text = str(value or '').strip()
    return text if text in SUPPORTED_THEME_IDS else DEFAULT_THEME_SETTINGS['selected_theme']


def _normalize_unique_symbol_list(values: Any) -> Any:
    """Normalize ticker-like values into an uppercase unique list."""
    normalized = []
    if not isinstance(values, list):
        return normalized
    for value in values:
        text = str(value or '').upper().strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_chart_slots_impl(chart_slots: Any, *, allow_empty: bool) -> Any:
    """Normalize chart slots into the persisted three-slot shape."""
    slots = _normalize_unique_symbol_list(chart_slots)
    if not slots and not allow_empty:
        slots = list(DEFAULT_CHART_SLOTS)
    while len(slots) < len(DEFAULT_CHART_SLOTS):
        slots.append(DEFAULT_CHART_SLOTS[len(slots)])
    return slots[:len(DEFAULT_CHART_SLOTS)]


def _normalize_chart_slots(chart_slots: Any) -> Any:
    """Normalize chart slots into the persisted three-slot shape."""
    return _normalize_chart_slots_impl(chart_slots, allow_empty=False)


def _normalize_portfolio_names(raw_names: Any) -> Any:
    """Normalize saved portfolio names for all fixed portfolio slots."""
    names = {}
    raw = raw_names if isinstance(raw_names, dict) else {}
    for index, portfolio_id in enumerate(PORTFOLIO_IDS):
        fallback = f'Portfolio {index + 1}'
        text = str(raw.get(portfolio_id, fallback) or fallback).strip()
        names[portfolio_id] = text or fallback
    return names


def _empty_multi_portfolio_payload(chart_slots: Any=None) -> Any:
    """Create an empty normalized multi-portfolio payload."""
    return {'chart_slots': _normalize_chart_slots(chart_slots), 'portfolios': {portfolio_id: [] for portfolio_id in PORTFOLIO_IDS}}


def _normalize_multi_ticker_payload(data: Any, chart_slots: Any=None) -> Any:
    """Normalize portfolio tickers into the multi-portfolio schema."""
    payload = _empty_multi_portfolio_payload(chart_slots)
    if isinstance(data, dict) and isinstance(data.get('portfolios'), dict):
        payload['chart_slots'] = _normalize_chart_slots(data.get('chart_slots'))
        for portfolio_id in PORTFOLIO_IDS:
            raw_tickers = data.get('portfolios', {}).get(portfolio_id, [])
            if isinstance(raw_tickers, dict):
                raw_tickers = raw_tickers.get('tickers', [])
            payload['portfolios'][portfolio_id] = _normalize_unique_symbol_list(raw_tickers)
        return payload
    legacy = _portfolio_payload_with_chart_slots(data, chart_slots)
    payload['chart_slots'] = _normalize_chart_slots(legacy.get('chart_slots'))
    payload['portfolios'][DEFAULT_MAIN_PORTFOLIO_ID] = _normalize_unique_symbol_list(legacy.get('portfolio', []))
    return payload


def _normalize_multi_tracker_payload(data: Any) -> Any:
    """Normalize tracker data into the multi-portfolio schema."""
    payload = {'portfolios': {portfolio_id: {} for portfolio_id in PORTFOLIO_IDS}}
    if isinstance(data, dict) and isinstance(data.get('portfolios'), dict):
        for portfolio_id in PORTFOLIO_IDS:
            raw_tracker = data.get('portfolios', {}).get(portfolio_id, {})
            payload['portfolios'][portfolio_id] = dict(raw_tracker) if isinstance(raw_tracker, dict) else {}
        return payload
    payload['portfolios'][DEFAULT_MAIN_PORTFOLIO_ID] = dict(data) if isinstance(data, dict) else {}
    return payload


def _normalize_multi_options_payload(data: Any) -> Any:
    """Normalize options positions into the multi-portfolio schema."""
    payload = {'portfolios': {portfolio_id: [] for portfolio_id in PORTFOLIO_IDS}}
    if isinstance(data, dict) and isinstance(data.get('portfolios'), dict):
        for portfolio_id in PORTFOLIO_IDS:
            raw_options = data.get('portfolios', {}).get(portfolio_id, [])
            payload['portfolios'][portfolio_id] = list(raw_options) if isinstance(raw_options, list) else []
        return payload
    payload['portfolios'][DEFAULT_MAIN_PORTFOLIO_ID] = list(data) if isinstance(data, list) else []
    return payload


def _normalize_portfolio_state(state: Any, chart_slots: Any=None) -> Any:
    """Normalize runtime portfolio state into the canonical three-portfolio structure."""
    base = _empty_multi_portfolio_payload(chart_slots)
    raw_state = state if isinstance(state, dict) else {}
    manager = raw_state.get('portfolio_manager', raw_state)
    names = _normalize_portfolio_names(raw_state.get('names', manager.get('names')))
    main_portfolio_id = _normalize_portfolio_id(raw_state.get('main_portfolio_id', manager.get('main_portfolio_id')))
    active_portfolio_id = _normalize_portfolio_id(raw_state.get('active_portfolio_id', manager.get('active_portfolio_id', main_portfolio_id)))
    base['chart_slots'] = _normalize_chart_slots(raw_state.get('chart_slots', chart_slots))
    raw_portfolios = raw_state.get('portfolios', {})
    if not isinstance(raw_portfolios, dict):
        raw_portfolios = {}
    portfolios = {}
    for portfolio_id in PORTFOLIO_IDS:
        raw_entry = raw_portfolios.get(portfolio_id, {})
        if not isinstance(raw_entry, dict):
            raw_entry = {}
        tracker_data = dict(raw_entry.get('tracker_data', {})) if isinstance(raw_entry.get('tracker_data', {}), dict) else {}
        options_data = list(raw_entry.get('options_data', [])) if isinstance(raw_entry.get('options_data', []), list) else []
        portfolios[portfolio_id] = {
            'name': names[portfolio_id],
            'tickers': _normalize_unique_symbol_list(raw_entry.get('tickers', raw_entry.get('portfolio', []))),
            'tracker_data': tracker_data,
            'options_data': options_data,
        }
    return {
        'chart_slots': base['chart_slots'],
        'main_portfolio_id': main_portfolio_id,
        'active_portfolio_id': active_portfolio_id,
        'portfolios': portfolios,
    }


def _sanitize_chart_slots(chart_slots: Any=None) -> Any:
    """Normalize chart-slot input into the persisted 3-slot shape."""
    return _normalize_chart_slots_impl(chart_slots, allow_empty=True)


def _default_portfolio_entry(portfolio_id: Any, chart_slots: Any=None) -> Any:
    """Build an empty normalized portfolio entry."""
    return {
        'id': portfolio_id,
        'name': DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, str(portfolio_id or DEFAULT_MAIN_PORTFOLIO_ID)),
        'portfolio': [],
        'chart_slots': _sanitize_chart_slots(chart_slots),
        'portfolio_tracker': {},
        'options_tracker': [],
    }


def _normalize_portfolio_name(portfolio_id: Any, name: Any) -> Any:
    """Return a safe user-visible portfolio name."""
    text = str(name or '').strip()
    return text if text else DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, str(portfolio_id or DEFAULT_MAIN_PORTFOLIO_ID))


def _normalize_portfolio_catalog(raw_catalog: Any) -> Any:
    """Normalize metadata for the fixed set of supported portfolios."""
    catalog = {}
    source = raw_catalog if isinstance(raw_catalog, dict) else {}
    for portfolio_id in PORTFOLIO_IDS:
        entry = source.get(portfolio_id, {})
        if not isinstance(entry, dict):
            entry = {}
        catalog[portfolio_id] = {
            'id': portfolio_id,
            'name': _normalize_portfolio_name(portfolio_id, entry.get('name')),
        }
    return catalog


def _normalize_main_portfolio_id(portfolio_id: Any) -> Any:
    """Clamp a selected portfolio id to a supported fixed slot."""
    portfolio_id = str(portfolio_id or '').strip()
    return portfolio_id if portfolio_id in PORTFOLIO_IDS else DEFAULT_MAIN_PORTFOLIO_ID


def _normalize_portfolio_storage(data: Any) -> Any:
    """Normalize portfolio.json data into the multi-portfolio schema."""
    normalized = {portfolio_id: _default_portfolio_entry(portfolio_id) for portfolio_id in PORTFOLIO_IDS}
    main_portfolio_id = DEFAULT_MAIN_PORTFOLIO_ID
    if isinstance(data, dict) and isinstance(data.get('portfolios'), dict):
        main_portfolio_id = _normalize_main_portfolio_id(data.get('main_portfolio_id'))
        for portfolio_id in PORTFOLIO_IDS:
            entry = data['portfolios'].get(portfolio_id, {})
            if not isinstance(entry, dict):
                entry = {}
            payload = _portfolio_payload_with_chart_slots(entry, normalized[portfolio_id]['chart_slots'])
            normalized[portfolio_id]['portfolio'] = list(payload.get('portfolio', []))
            normalized[portfolio_id]['chart_slots'] = _sanitize_chart_slots(payload.get('chart_slots'))
    elif isinstance(data, dict) or isinstance(data, list):
        payload = _portfolio_payload_with_chart_slots(data)
        normalized[DEFAULT_MAIN_PORTFOLIO_ID]['portfolio'] = list(payload.get('portfolio', []))
        normalized[DEFAULT_MAIN_PORTFOLIO_ID]['chart_slots'] = _sanitize_chart_slots(payload.get('chart_slots'))
    return {'version': MULTI_PORTFOLIO_VERSION, 'main_portfolio_id': main_portfolio_id, 'portfolios': normalized}


def _normalize_tracker_storage(data: Any) -> Any:
    """Normalize portfolio_tracker.json data into the multi-portfolio schema."""
    normalized = {portfolio_id: {} for portfolio_id in PORTFOLIO_IDS}
    if isinstance(data, dict) and isinstance(data.get('portfolios'), dict):
        for portfolio_id in PORTFOLIO_IDS:
            tracker = data['portfolios'].get(portfolio_id, {})
            normalized[portfolio_id] = tracker if isinstance(tracker, dict) else {}
    elif isinstance(data, dict):
        normalized[DEFAULT_MAIN_PORTFOLIO_ID] = data
    return {'version': MULTI_PORTFOLIO_VERSION, 'portfolios': normalized}


def _normalize_options_storage(data: Any) -> Any:
    """Normalize options_tracker.json data into the multi-portfolio schema."""
    normalized = {portfolio_id: [] for portfolio_id in PORTFOLIO_IDS}
    if isinstance(data, dict) and isinstance(data.get('portfolios'), dict):
        for portfolio_id in PORTFOLIO_IDS:
            options_payload = data['portfolios'].get(portfolio_id, [])
            normalized[portfolio_id] = list(options_payload) if isinstance(options_payload, list) else []
    elif isinstance(data, list):
        normalized[DEFAULT_MAIN_PORTFOLIO_ID] = list(data)
    return {'version': MULTI_PORTFOLIO_VERSION, 'portfolios': normalized}


def _normalize_multi_portfolio_state(payload: Any, chart_slots: Any=None) -> Any:
    """Normalize a mixed old/new payload into the runtime multi-portfolio shape."""
    normalized = {
        'version': MULTI_PORTFOLIO_VERSION,
        'main_portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID,
        'active_portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID,
        'portfolios': {portfolio_id: _default_portfolio_entry(portfolio_id, chart_slots if portfolio_id == DEFAULT_MAIN_PORTFOLIO_ID else None) for portfolio_id in PORTFOLIO_IDS},
    }
    if not isinstance(payload, dict):
        return normalized
    normalized['main_portfolio_id'] = _normalize_main_portfolio_id(payload.get('main_portfolio_id'))
    normalized['active_portfolio_id'] = _normalize_main_portfolio_id(payload.get('active_portfolio_id', normalized['main_portfolio_id']))
    metadata = _normalize_portfolio_catalog(payload.get('portfolio_catalog') or payload.get('portfolios'))
    portfolio_map = payload.get('portfolios', {})
    if not isinstance(portfolio_map, dict):
        portfolio_map = {}
    for portfolio_id in PORTFOLIO_IDS:
        meta_entry = metadata.get(portfolio_id, {})
        raw_entry = portfolio_map.get(portfolio_id, {})
        if not isinstance(raw_entry, dict):
            raw_entry = {}
        portfolio_payload = _portfolio_payload_with_chart_slots(raw_entry.get('portfolio', raw_entry), raw_entry.get('chart_slots'))
        tracker_payload = raw_entry.get('portfolio_tracker', raw_entry.get('tracker_data', {}))
        options_payload = raw_entry.get('options_tracker', raw_entry.get('options_data', []))
        normalized['portfolios'][portfolio_id] = {
            'id': portfolio_id,
            'name': _normalize_portfolio_name(portfolio_id, meta_entry.get('name') or raw_entry.get('name')),
            'portfolio': list(portfolio_payload.get('portfolio', [])),
            'chart_slots': _sanitize_chart_slots(portfolio_payload.get('chart_slots')),
            'portfolio_tracker': tracker_payload if isinstance(tracker_payload, dict) else {},
            'options_tracker': list(options_payload) if isinstance(options_payload, list) else [],
        }
    if 'portfolio' in payload or 'portfolio_tracker' in payload or 'options_tracker' in payload:
        legacy_portfolio = _portfolio_payload_with_chart_slots(payload.get('portfolio', []), chart_slots)
        legacy_tracker = payload.get('portfolio_tracker', {})
        legacy_options = payload.get('options_tracker', [])
        normalized['portfolios'][DEFAULT_MAIN_PORTFOLIO_ID] = {
            'id': DEFAULT_MAIN_PORTFOLIO_ID,
            'name': normalized['portfolios'][DEFAULT_MAIN_PORTFOLIO_ID]['name'],
            'portfolio': list(legacy_portfolio.get('portfolio', [])),
            'chart_slots': _sanitize_chart_slots(legacy_portfolio.get('chart_slots')),
            'portfolio_tracker': legacy_tracker if isinstance(legacy_tracker, dict) else {},
            'options_tracker': list(legacy_options) if isinstance(legacy_options, list) else [],
        }
    return normalized


def _serialize_portfolio_storage(state: Any) -> Any:
    """Build the on-disk portfolio.json payload from normalized state."""
    return {
        'version': MULTI_PORTFOLIO_VERSION,
        'main_portfolio_id': _normalize_main_portfolio_id(state.get('main_portfolio_id')),
        'active_portfolio_id': _normalize_main_portfolio_id(state.get('active_portfolio_id', state.get('main_portfolio_id'))),
        'portfolios': {
            portfolio_id: _portfolio_payload_with_chart_slots(
                state.get('portfolios', {}).get(portfolio_id, {}),
                state.get('portfolios', {}).get(portfolio_id, {}).get('chart_slots'),
            ) for portfolio_id in PORTFOLIO_IDS
        },
    }


def _serialize_tracker_storage(state: Any) -> Any:
    """Build the on-disk portfolio_tracker.json payload from normalized state."""
    return {
        'version': MULTI_PORTFOLIO_VERSION,
        'portfolios': {
            portfolio_id: dict(state.get('portfolios', {}).get(portfolio_id, {}).get('portfolio_tracker', {})) for portfolio_id in PORTFOLIO_IDS
        },
    }


def _serialize_options_storage(state: Any) -> Any:
    """Build the on-disk options_tracker.json payload from normalized state."""
    return {
        'version': MULTI_PORTFOLIO_VERSION,
        'portfolios': {
            portfolio_id: list(state.get('portfolios', {}).get(portfolio_id, {}).get('options_tracker', [])) for portfolio_id in PORTFOLIO_IDS
        },
    }


def _normalize_networth_payload(data: Any) -> Any:
    """Normalize persisted net-worth lists into the supported shape."""
    payload = data if isinstance(data, dict) else {}
    cash = payload.get('cash', [])
    pension_insurance = payload.get('pension_insurance', [])
    debt = payload.get('debt', [])
    return {
        'cash': list(cash) if isinstance(cash, list) else [],
        'pension_insurance': list(pension_insurance) if isinstance(pension_insurance, list) else [],
        'debt': list(debt) if isinstance(debt, list) else [],
    }


def _normalize_theme_payload(settings: Any) -> Any:
    """Normalize persisted theme settings for the single-file document."""
    saved = settings if isinstance(settings, dict) else {}
    return {'selected_theme': _normalize_theme_setting(saved.get('selected_theme'))}


def _normalize_options_chain_payload(settings: Any) -> Any:
    """Normalize persisted options-chain defaults for the single-file document."""
    saved = settings if isinstance(settings, dict) else {}
    rate = saved.get('default_risk_free_rate', DEFAULT_OPTIONS_CHAIN_SETTINGS['default_risk_free_rate'])
    try:
        rate_value = float(rate)
    except (TypeError, ValueError):
        rate_value = DEFAULT_OPTIONS_CHAIN_SETTINGS['default_risk_free_rate']
    return {'default_risk_free_rate': min(max(rate_value, 0.0), 1.0)}

def fmt_num(val: Any) -> Any:
    """Format large numbers with B/M/K suffix."""
    if val is None:
        return 'N/A'
    try:
        val = float(val)
        if pd.isna(val):
            return 'N/A'
    except (TypeError, ValueError):
        return 'N/A'
    neg = val < 0
    abs_val = abs(val)
    if abs_val >= 1000000000000.0:
        s = f'{abs_val / 1000000000000.0:.2f}T'
    elif abs_val >= 1000000000.0:
        s = f'{abs_val / 1000000000.0:.2f}B'
    elif abs_val >= 1000000.0:
        s = f'{abs_val / 1000000.0:.2f}M'
    elif abs_val >= 1000.0:
        s = f'{abs_val / 1000.0:.1f}K'
    else:
        s = f'{abs_val:.2f}'
    return f'-{s}' if neg else s


def _default_user_data_document() -> Any:
    """Build the default single-file user-data document."""
    portfolio_state = _normalize_multi_portfolio_state({})
    return {
        'version': USER_DATA_BACKUP_VERSION,
        'main_portfolio_id': portfolio_state['main_portfolio_id'],
        'active_portfolio_id': portfolio_state['active_portfolio_id'],
        'portfolios': portfolio_state['portfolios'],
        'chart_page': DEFAULT_CHART_PAGE_SETTINGS.copy(),
        'dashboard_chart': DEFAULT_DASHBOARD_CHART_SETTINGS.copy(),
        'net_worth': {'cash': [], 'pension_insurance': [], 'debt': []},
        'theme': DEFAULT_THEME_SETTINGS.copy(),
        'options_chain': DEFAULT_OPTIONS_CHAIN_SETTINGS.copy(),
        'time_12h': False,
    }


def _normalize_user_data_document(payload: Any) -> Any:
    """Normalize persisted single-file user data into the canonical shape."""
    default = _default_user_data_document()
    saved = payload if isinstance(payload, dict) else {}
    portfolio_state = _normalize_multi_portfolio_state(saved)
    return {
        'version': USER_DATA_BACKUP_VERSION,
        'main_portfolio_id': portfolio_state['main_portfolio_id'],
        'active_portfolio_id': portfolio_state.get('active_portfolio_id', portfolio_state['main_portfolio_id']),
        'portfolios': portfolio_state['portfolios'],
        'chart_page': _normalize_chart_page_settings(saved.get('chart_page', default['chart_page'])),
        'dashboard_chart': _normalize_dashboard_chart_settings(saved.get('dashboard_chart', default['dashboard_chart'])),
        'net_worth': _normalize_networth_payload(saved.get('net_worth', default['net_worth'])),
        'theme': _normalize_theme_payload(saved.get('theme', default['theme'])),
        'options_chain': _normalize_options_chain_payload(saved.get('options_chain', default['options_chain'])),
        'time_12h': bool(saved.get('time_12h', False)),
    }


def _load_legacy_user_data_document() -> Any:
    """Load the old Documents-based user-data file when present."""
    return _normalize_user_data_document(_read_json(LEGACY_USER_DATA_FILE, None))


def _migrate_legacy_user_data_file() -> Any:
    """Move the legacy Documents-based save file into LocalAppData once."""
    if Path(USER_DATA_FILE).exists():
        return None
    legacy_path = Path(LEGACY_USER_DATA_FILE)
    if not legacy_path.exists():
        return None
    normalized = _load_legacy_user_data_document()
    _write_json(USER_DATA_FILE, normalized, indent=2)
    try:
        legacy_path.unlink()
    except OSError:
        logger.warning('User data migrated to %s but the legacy file could not be removed: %s', USER_DATA_FILE, legacy_path)
    else:
        logger.info('Migrated user data from %s to %s.', legacy_path, USER_DATA_FILE)
    return normalized


def _load_user_data_document() -> Any:
    """Load the current single-file user-data document from LocalAppData."""
    migrated = _migrate_legacy_user_data_file()
    if migrated is not None:
        return migrated
    return _normalize_user_data_document(_read_json(USER_DATA_FILE, None))


def _save_user_data_document(data: Any) -> Any:
    """Persist the normalized single-file user-data document to LocalAppData."""
    normalized = _normalize_user_data_document(data)
    _write_json(USER_DATA_FILE, normalized, indent=2)
    return normalized


def load_all_portfolios_state() -> Any:
    """Load the normalized state for all supported portfolios."""
    document = _load_user_data_document()
    state = {
        'version': MULTI_PORTFOLIO_VERSION,
        'main_portfolio_id': _normalize_main_portfolio_id(document.get('main_portfolio_id')),
        'active_portfolio_id': _normalize_main_portfolio_id(document.get('active_portfolio_id', document.get('main_portfolio_id'))),
        'portfolios': {},
    }
    for portfolio_id in PORTFOLIO_IDS:
        portfolio_entry = document.get('portfolios', {}).get(portfolio_id, _default_portfolio_entry(portfolio_id))
        state['portfolios'][portfolio_id] = {
            'id': portfolio_id,
            'name': _normalize_portfolio_name(portfolio_id, portfolio_entry.get('name')),
            'portfolio': list(portfolio_entry.get('portfolio', [])),
            'chart_slots': _sanitize_chart_slots(portfolio_entry.get('chart_slots')),
            'portfolio_tracker': dict(portfolio_entry.get('portfolio_tracker', {})) if isinstance(portfolio_entry.get('portfolio_tracker', {}), dict) else {},
            'options_tracker': list(portfolio_entry.get('options_tracker', [])) if isinstance(portfolio_entry.get('options_tracker', []), list) else [],
        }
    return state


def save_all_portfolios_state(state: Any) -> Any:
    """Persist the normalized state for all supported portfolios."""
    normalized = _normalize_multi_portfolio_state(state)
    document = _load_user_data_document()
    document['main_portfolio_id'] = normalized['main_portfolio_id']
    document['active_portfolio_id'] = normalized.get('active_portfolio_id', normalized['main_portfolio_id'])
    document['portfolios'] = normalized['portfolios']
    _save_user_data_document(document)
    return normalized


def load_active_portfolio_state(portfolio_id: Any=None) -> Any:
    """Load one normalized portfolio state."""
    state = load_all_portfolios_state()
    active_id = _normalize_main_portfolio_id(portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    active = state['portfolios'][active_id]
    return {
        'main_portfolio_id': active_id,
        'portfolio_id': active_id,
        'portfolio_name': active.get('name', DEFAULT_PORTFOLIO_NAMES.get(active_id, active_id)),
        'portfolio': list(active.get('portfolio', [])),
        'chart_slots': _sanitize_chart_slots(active.get('chart_slots')),
        'portfolio_tracker': dict(active.get('portfolio_tracker', {})),
        'options_tracker': list(active.get('options_tracker', [])),
    }

def load_tickers() -> Any:
    """Load tickers."""
    state = load_active_portfolio_state()
    tickers = state.get('portfolio', [])
    chart_slots = state.get('chart_slots', list(DEFAULT_CHART_SLOTS))
    if tickers:
        return (tickers, chart_slots)
    return (['AAPL', 'MSFT', 'GOOGL', 'TSLA'], chart_slots)

def save_tickers(portfolio: Any, chart_slots: Any=None, portfolio_id: Any=None) -> None:
    """Save tickers."""
    state = load_all_portfolios_state()
    active_id = _normalize_main_portfolio_id(portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['portfolio'] = list(portfolio) if isinstance(portfolio, list) else []
    state['portfolios'][active_id]['chart_slots'] = _sanitize_chart_slots(chart_slots if chart_slots is not None else state['portfolios'][active_id].get('chart_slots'))
    save_all_portfolios_state(state)

def load_tracker_data(portfolio_id: Any=None) -> Any:
    """Load tracker data."""
    return load_active_portfolio_state(portfolio_id).get('portfolio_tracker', {})

def save_tracker_data(data: Any, portfolio_id: Any=None) -> None:
    """Save tracker data."""
    state = load_all_portfolios_state()
    active_id = _normalize_main_portfolio_id(portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['portfolio_tracker'] = data if isinstance(data, dict) else {}
    save_all_portfolios_state(state)

def load_options_data(portfolio_id: Any=None) -> Any:
    """Load options data."""
    return load_active_portfolio_state(portfolio_id).get('options_tracker', [])

def save_options_data(data: Any, portfolio_id: Any=None) -> None:
    """Save options data."""
    state = load_all_portfolios_state()
    active_id = _normalize_main_portfolio_id(portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['options_tracker'] = list(data) if isinstance(data, list) else []
    save_all_portfolios_state(state)

def load_networth_data() -> Any:
    """Load networth data."""
    return _normalize_networth_payload(_load_user_data_document().get('net_worth'))

def save_networth_data(data: Any) -> None:
    """Save networth data."""
    document = _load_user_data_document()
    document['net_worth'] = _normalize_networth_payload(data)
    _save_user_data_document(document)


def build_user_data_backup() -> Any:
    """Build a single-file backup payload for all persisted user data."""
    backup = _load_user_data_document()
    backup['version'] = USER_DATA_BACKUP_VERSION
    backup['exported_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return backup


def export_user_data_backup(path: Any) -> None:
    """Write the current backup payload to a single JSON file."""
    _write_json(path, build_user_data_backup(), indent=2)


def _json_block(data: Any) -> Any:
    """Render a JSON code block for human and AI-readable exports."""
    return f"```json\n{json.dumps(data, indent=2)}\n```"


def build_ai_user_data_export() -> str:
    """Build a Markdown export optimized for human and AI analysis."""
    payload = build_user_data_backup()
    lines = [
        '# Budget Terminal User Data',
        '',
        f"- Exported at: {payload.get('exported_at', '')}",
        f"- Main portfolio: {payload.get('main_portfolio_id', DEFAULT_MAIN_PORTFOLIO_ID)}",
        f"- Active portfolio: {payload.get('active_portfolio_id', DEFAULT_MAIN_PORTFOLIO_ID)}",
        '',
        '## Portfolio Summary',
        '',
    ]
    portfolios = payload.get('portfolios', {})
    for portfolio_id in PORTFOLIO_IDS:
        entry = portfolios.get(portfolio_id, {})
        name = str(entry.get('name', DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)) or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id))
        tickers = list(entry.get('portfolio', []))
        tracker = dict(entry.get('portfolio_tracker', {})) if isinstance(entry.get('portfolio_tracker', {}), dict) else {}
        options_data = list(entry.get('options_tracker', [])) if isinstance(entry.get('options_tracker', []), list) else []
        lines.extend([
            f"### {name} ({portfolio_id})",
            '',
            f"- Ticker count: {len(tickers)}",
            f"- Tracker rows: {len(tracker)}",
            f"- Options positions: {len(options_data)}",
            f"- Chart slots: {', '.join(list(entry.get('chart_slots', [])))}",
            '',
            '**Tickers**',
            '',
            _json_block(tickers),
            '',
            '**Tracker Data**',
            '',
            _json_block(tracker),
            '',
            '**Options Data**',
            '',
            _json_block(options_data),
            '',
        ])
    lines.extend([
        '## Net Worth',
        '',
        _json_block(payload.get('net_worth', {'cash': [], 'debt': []})),
        '',
        '## Charts Page Settings',
        '',
        _json_block(payload.get('chart_page', DEFAULT_CHART_PAGE_SETTINGS)),
        '',
        '## Dashboard Chart Settings',
        '',
        _json_block(payload.get('dashboard_chart', DEFAULT_DASHBOARD_CHART_SETTINGS)),
        '',
        '## Theme Settings',
        '',
        _json_block(payload.get('theme', DEFAULT_THEME_SETTINGS)),
        '',
        '## Options Chain Settings',
        '',
        _json_block(payload.get('options_chain', DEFAULT_OPTIONS_CHAIN_SETTINGS)),
        '',
        '## Full Normalized Payload',
        '',
        _json_block(payload),
        '',
    ])
    return '\n'.join(lines)


def export_ai_user_data(path: Any) -> None:
    """Write an AI-friendly Markdown export of the current user data."""
    Path(path).write_text(build_ai_user_data_export(), encoding='utf-8')


def _validate_backup_payload(payload: Any) -> Any:
    """Validate imported backup data and return a normalized payload."""
    if not isinstance(payload, dict):
        raise ValueError('Backup file must contain a JSON object.')
    has_multi_portfolios = isinstance(payload.get('portfolios'), dict)
    has_legacy_payload = any((key in payload for key in ('portfolio', 'portfolio_tracker', 'options_tracker')))
    if not has_multi_portfolios and not has_legacy_payload:
        raise ValueError('Backup file is missing portfolio data.')
    if 'net_worth' in payload:
        networth_payload = payload.get('net_worth')
        if not isinstance(networth_payload, dict):
            raise ValueError('Backup net worth data must be a JSON object.')
        if not isinstance(networth_payload.get('cash', []), list) or not isinstance(networth_payload.get('pension_insurance', []), list) or not isinstance(networth_payload.get('debt', []), list):
            raise ValueError('Backup net worth data must include cash, pension_insurance, and debt lists.')
    return _normalize_user_data_document(payload)


def load_user_data_backup(path: Any) -> Any:
    """Load and validate a single-file backup payload."""
    payload = _read_json(path, None)
    if payload is None:
        raise ValueError('Unable to read backup file.')
    return _validate_backup_payload(payload)


def apply_user_data_backup(payload: Any) -> Any:
    """Persist validated backup data and return the normalized state."""
    normalized = _validate_backup_payload(payload)
    return _save_user_data_document(normalized)


def reset_user_data(chart_slots: Any=None) -> Any:
    """Persist a cleared user-data state while preserving chart slots."""
    normalized = {
        'main_portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID,
        'active_portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID,
        'portfolios': {
            portfolio_id: _default_portfolio_entry(portfolio_id, chart_slots if portfolio_id == DEFAULT_MAIN_PORTFOLIO_ID else None) for portfolio_id in PORTFOLIO_IDS
        },
        'chart_page': DEFAULT_CHART_PAGE_SETTINGS.copy(),
        'dashboard_chart': DEFAULT_DASHBOARD_CHART_SETTINGS.copy(),
        'net_worth': {'cash': [], 'pension_insurance': [], 'debt': []},
        'theme': DEFAULT_THEME_SETTINGS.copy(),
        'options_chain': DEFAULT_OPTIONS_CHAIN_SETTINGS.copy(),
        'time_12h': False,
    }
    return apply_user_data_backup(normalized)


def load_app_config() -> Any:
    """Load app-level config data."""
    document = _load_user_data_document()
    return {
        'portfolio_state': {
            'main_portfolio_id': document['main_portfolio_id'],
            'active_portfolio_id': document.get('active_portfolio_id', document['main_portfolio_id']),
            'portfolios': {portfolio_id: {'name': entry.get('name')} for portfolio_id, entry in document.get('portfolios', {}).items()},
        },
        'theme': dict(document.get('theme', DEFAULT_THEME_SETTINGS)),
        'chart_page': dict(document.get('chart_page', DEFAULT_CHART_PAGE_SETTINGS)),
        'dashboard_chart': dict(document.get('dashboard_chart', DEFAULT_DASHBOARD_CHART_SETTINGS)),
        'multi_charts': dict(document.get('multi_charts', {})),
        'options_chain': dict(document.get('options_chain', DEFAULT_OPTIONS_CHAIN_SETTINGS)),
        'time_12h': bool(document.get('time_12h', False)),
    }


def save_app_config(data: Any) -> None:
    """Persist app-level config data."""
    current = _load_user_data_document()
    saved = data if isinstance(data, dict) else {}
    portfolio_state = saved.get('portfolio_state', {})
    if isinstance(portfolio_state, dict):
        current['main_portfolio_id'] = _normalize_main_portfolio_id(portfolio_state.get('main_portfolio_id', current['main_portfolio_id']))
        current['active_portfolio_id'] = _normalize_main_portfolio_id(portfolio_state.get('active_portfolio_id', current.get('active_portfolio_id', current['main_portfolio_id'])))
        names = _normalize_portfolio_catalog(portfolio_state.get('portfolios'))
        portfolio_map = current.get('portfolios', {})
        for portfolio_id in PORTFOLIO_IDS:
            entry = portfolio_map.setdefault(portfolio_id, _default_portfolio_entry(portfolio_id))
            entry['name'] = names.get(portfolio_id, {}).get('name', entry.get('name'))
    if 'theme' in saved:
        current['theme'] = _normalize_theme_payload(saved.get('theme'))
    if 'chart_page' in saved:
        current['chart_page'] = _normalize_chart_page_settings(saved.get('chart_page'))
    if 'dashboard_chart' in saved:
        current['dashboard_chart'] = _normalize_dashboard_chart_settings(saved.get('dashboard_chart'))
    if 'multi_charts' in saved:
        raw_multi = saved.get('multi_charts', {})
        raw_multi = raw_multi if isinstance(raw_multi, dict) else {}
        current['multi_charts'] = {
            'custom_symbols': _normalize_unique_symbol_list(raw_multi.get('custom_symbols', [])),
            'order': _normalize_unique_symbol_list(raw_multi.get('order', [])),
        }
    if 'options_chain' in saved:
        current['options_chain'] = _normalize_options_chain_payload(saved.get('options_chain'))
    if 'time_12h' in saved:
        current['time_12h'] = bool(saved['time_12h'])
    _save_user_data_document(current)


def _normalize_indicator_list(raw_indicators: Any, default_indicators: Any, *, ensure_ma200: bool=False) -> Any:
    """Normalize indicator selections into the supported canonical labels."""
    indicators_source = raw_indicators if isinstance(raw_indicators, list) else list(default_indicators)
    indicators = []
    for name in indicators_source:
        text = str(name or '').strip()
        normalized = text.upper().replace(' ', '')
        if normalized == 'VOLUME':
            text = 'Volume'
        elif normalized == 'RSI':
            text = 'RSI'
        elif normalized in ('200MA', 'MA200'):
            text = '200 MA'
        else:
            text = ''
        if text and text not in indicators:
            indicators.append(text)
    if ensure_ma200 and '200 MA' not in indicators:
        indicators.append('200 MA')
    ordered = []
    for indicator in ('Volume', 'RSI', '200 MA'):
        if indicator in indicators and indicator not in ordered:
            ordered.append(indicator)
    return ordered or list(default_indicators)


def _normalize_chart_page_settings(settings: Any) -> Any:
    """Normalize persisted state for the dedicated Charts page."""
    saved = settings if isinstance(settings, dict) else {}
    symbol = str(saved.get('symbol', DEFAULT_CHART_PAGE_SETTINGS['symbol']) or DEFAULT_CHART_PAGE_SETTINGS['symbol']).upper()
    timeframe_label = str(saved.get('timeframe_label', DEFAULT_CHART_PAGE_SETTINGS['timeframe_label']) or DEFAULT_CHART_PAGE_SETTINGS['timeframe_label'])
    raw_watchlist = saved.get('watchlist', [])
    if not isinstance(raw_watchlist, list):
        raw_watchlist = []
    watchlist = _normalize_unique_symbol_list(raw_watchlist)
    indicators = _normalize_indicator_list(saved.get('indicators'), DEFAULT_CHART_PAGE_SETTINGS['indicators'])
    auto_value = saved.get('auto', DEFAULT_CHART_PAGE_SETTINGS['auto'])
    auto_enabled = bool(auto_value) if isinstance(auto_value, bool | int) else DEFAULT_CHART_PAGE_SETTINGS['auto']
    return {'symbol': symbol, 'timeframe_label': timeframe_label, 'watchlist': watchlist, 'indicators': indicators, 'auto': auto_enabled}


def _normalize_dashboard_chart_settings(settings: Any) -> Any:
    """Normalize persisted state for the dashboard chart workstation."""
    saved = settings if isinstance(settings, dict) else {}
    symbol = str(saved.get('symbol', DEFAULT_DASHBOARD_CHART_SETTINGS['symbol']) or DEFAULT_DASHBOARD_CHART_SETTINGS['symbol']).upper().strip()
    timeframe_label = str(saved.get('timeframe_label', DEFAULT_DASHBOARD_CHART_SETTINGS['timeframe_label']) or DEFAULT_DASHBOARD_CHART_SETTINGS['timeframe_label']).strip()
    indicators = _normalize_indicator_list(
        saved.get('indicators'),
        DEFAULT_DASHBOARD_CHART_SETTINGS['indicators'],
        ensure_ma200=True,
    )
    auto_value = saved.get('auto', DEFAULT_DASHBOARD_CHART_SETTINGS['auto'])
    auto_enabled = bool(auto_value) if isinstance(auto_value, bool | int) else DEFAULT_DASHBOARD_CHART_SETTINGS['auto']
    raw_splitter_sizes = saved.get('splitter_sizes', DEFAULT_DASHBOARD_CHART_SETTINGS['splitter_sizes'])
    splitter_sizes = []
    if isinstance(raw_splitter_sizes, list):
        for value in raw_splitter_sizes[:2]:
            try:
                size = max(int(value), 1)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                splitter_sizes.append(size)
    if len(splitter_sizes) != 2:
        splitter_sizes = list(DEFAULT_DASHBOARD_CHART_SETTINGS['splitter_sizes'])
    raw_main_splitter = saved.get('main_splitter_sizes', DEFAULT_DASHBOARD_CHART_SETTINGS['main_splitter_sizes'])
    main_splitter_sizes = []
    if isinstance(raw_main_splitter, list):
        for value in raw_main_splitter[:2]:
            try:
                size = max(int(value), 1)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                main_splitter_sizes.append(size)
    if len(main_splitter_sizes) != 2:
        main_splitter_sizes = list(DEFAULT_DASHBOARD_CHART_SETTINGS['main_splitter_sizes'])
    return {
        'symbol': symbol or DEFAULT_DASHBOARD_CHART_SETTINGS['symbol'],
        'timeframe_label': timeframe_label or DEFAULT_DASHBOARD_CHART_SETTINGS['timeframe_label'],
        'indicators': indicators,
        'auto': auto_enabled,
        'splitter_sizes': splitter_sizes,
        'main_splitter_sizes': main_splitter_sizes,
    }


def normalize_dashboard_chart_settings(settings: Any) -> Any:
    """Public wrapper for dashboard chart state normalization."""
    return _normalize_dashboard_chart_settings(settings)


def load_portfolio_preferences() -> Any:
    """Load portfolio metadata and selected main/active portfolio ids from app config."""
    config = load_app_config()
    saved = config.get('portfolio_state', {})
    if not isinstance(saved, dict):
        saved = {}
    catalog = _normalize_portfolio_catalog(saved.get('portfolios'))
    main_portfolio_id = _normalize_main_portfolio_id(saved.get('main_portfolio_id'))
    active_portfolio_id = _normalize_main_portfolio_id(saved.get('active_portfolio_id', main_portfolio_id))
    return {'main_portfolio_id': main_portfolio_id, 'active_portfolio_id': active_portfolio_id, 'portfolios': catalog}


def save_portfolio_preferences(settings: Any) -> Any:
    """Persist portfolio metadata and selected main/active portfolio ids in app config."""
    current = load_app_config()
    state = load_portfolio_preferences()
    if isinstance(settings, dict):
        state['main_portfolio_id'] = _normalize_main_portfolio_id(settings.get('main_portfolio_id', state['main_portfolio_id']))
        state['active_portfolio_id'] = _normalize_main_portfolio_id(settings.get('active_portfolio_id', state.get('active_portfolio_id', state['main_portfolio_id'])))
        state['portfolios'] = _normalize_portfolio_catalog(settings.get('portfolios', state['portfolios']))
    current['portfolio_state'] = {
        'main_portfolio_id': state['main_portfolio_id'],
        'active_portfolio_id': state['active_portfolio_id'],
        'portfolios': state['portfolios'],
    }
    save_app_config(current)
    return state


def load_theme_settings() -> Any:
    """Load persisted UI theme preferences."""
    config = load_app_config()
    saved = config.get('theme', {})
    if not isinstance(saved, dict):
        saved = {}
    return {'selected_theme': _normalize_theme_setting(saved.get('selected_theme'))}


def save_theme_settings(settings: Any) -> Any:
    """Persist UI theme preferences in app config."""
    current = load_app_config()
    payload = load_theme_settings()
    if isinstance(settings, dict):
        payload['selected_theme'] = _normalize_theme_setting(settings.get('selected_theme', payload['selected_theme']))
    current['theme'] = payload
    save_app_config(current)
    return payload


def load_chart_page_settings() -> Any:
    """Load persisted state for the dedicated Charts page."""
    config = load_app_config()
    return _normalize_chart_page_settings(config.get('chart_page', {}))


def save_chart_page_settings(settings: Any) -> Any:
    """Persist state for the dedicated Charts page."""
    current = load_app_config()
    state = _normalize_chart_page_settings(settings)
    current['chart_page'] = state
    save_app_config(current)
    return state


def load_dashboard_chart_settings() -> Any:
    """Load persisted state for the dashboard chart workstation."""
    config = load_app_config()
    return _normalize_dashboard_chart_settings(config.get('dashboard_chart', {}))


def save_dashboard_chart_settings(settings: Any) -> Any:
    """Persist state for the dashboard chart workstation."""
    current = load_app_config()
    state = _normalize_dashboard_chart_settings(settings)
    current['dashboard_chart'] = state
    save_app_config(current)
    return state


def load_multi_charts_settings() -> Any:
    """Load persisted state for the Multi Charts page."""
    config = load_app_config()
    saved = config.get('multi_charts', {})
    if not isinstance(saved, dict):
        saved = {}
    return {
        'custom_symbols': _normalize_unique_symbol_list(saved.get('custom_symbols', [])),
        'order': _normalize_unique_symbol_list(saved.get('order', [])),
    }


def save_multi_charts_settings(settings: Any) -> None:
    """Persist state for the Multi Charts page."""
    current = load_app_config()
    payload = settings if isinstance(settings, dict) else {}
    current['multi_charts'] = {
        'custom_symbols': _normalize_unique_symbol_list(payload.get('custom_symbols', [])),
        'order': _normalize_unique_symbol_list(payload.get('order', [])),
    }
    save_app_config(current)


def load_options_chain_settings() -> Any:
    """Load persisted defaults for options-chain analytics."""
    config = load_app_config()
    saved = config.get('options_chain', {})
    if not isinstance(saved, dict):
        saved = {}
    rate = saved.get('default_risk_free_rate', DEFAULT_OPTIONS_CHAIN_SETTINGS['default_risk_free_rate'])
    try:
        rate_value = float(rate)
    except (TypeError, ValueError):
        rate_value = DEFAULT_OPTIONS_CHAIN_SETTINGS['default_risk_free_rate']
    rate_value = min(max(rate_value, 0.0), 1.0)
    return {'default_risk_free_rate': rate_value}


def save_options_chain_settings(settings: Any) -> Any:
    """Persist defaults for options-chain analytics."""
    current = load_app_config()
    state = DEFAULT_OPTIONS_CHAIN_SETTINGS.copy()
    if isinstance(settings, dict):
        raw_rate = settings.get('default_risk_free_rate', state['default_risk_free_rate'])
        try:
            state['default_risk_free_rate'] = min(max(float(raw_rate), 0.0), 1.0)
        except (TypeError, ValueError):
            state['default_risk_free_rate'] = DEFAULT_OPTIONS_CHAIN_SETTINGS['default_risk_free_rate']
    current['options_chain'] = state
    save_app_config(current)
    return state


def load_time_format() -> bool:
    """Load persisted 12h/24h time format preference."""
    config = load_app_config()
    return bool(config.get('time_12h', False))


def save_time_format(use_12h: bool) -> None:
    """Persist 12h/24h time format preference."""
    save_app_config({'time_12h': bool(use_12h)})
