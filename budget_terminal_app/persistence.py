from __future__ import annotations
from typing import Any
from .dependencies import *

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CHART_SLOTS = ['AAPL', 'TSLA', 'NVDA']
USER_DATA_BACKUP_VERSION = 2
APP_CONFIG_FILE = BASE_DIR / 'budget_terminal_app' / 'config.json'
DEFAULT_CHART_PAGE_SETTINGS = {'symbol': 'SPY', 'timeframe_label': '1 Day', 'watchlist': [], 'indicators': ['Volume', '200 MA'], 'auto': True}
DEFAULT_OPTIONS_CHAIN_SETTINGS = {'default_risk_free_rate': 0.04}
MAX_PORTFOLIOS = 3
MULTI_PORTFOLIO_VERSION = 2
PORTFOLIO_IDS = [f'portfolio_{index}' for index in range(1, MAX_PORTFOLIOS + 1)]
DEFAULT_MAIN_PORTFOLIO_ID = PORTFOLIO_IDS[0]
DEFAULT_PORTFOLIO_NAMES = {portfolio_id: f'Portfolio {index}' for index, portfolio_id in enumerate(PORTFOLIO_IDS, start=1)}


def _read_json(path: Any, default: Any) -> Any:
    """Read JSON from disk, returning a fallback on failure."""
    try:
        with Path(path).open() as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: Any, data: Any, *, indent: Any=None) -> None:
    """Write JSON data to disk."""
    with Path(path).open('w') as f:
        json.dump(data, f, indent=indent)


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


def _normalize_chart_slots(chart_slots: Any) -> Any:
    """Normalize chart slots into the persisted three-slot shape."""
    slots = []
    if isinstance(chart_slots, list):
        for value in chart_slots:
            text = str(value or '').upper().strip()
            slots.append(text)
    if not slots:
        slots = list(DEFAULT_CHART_SLOTS)
    while len(slots) < len(DEFAULT_CHART_SLOTS):
        slots.append(DEFAULT_CHART_SLOTS[len(slots)])
    return slots[:len(DEFAULT_CHART_SLOTS)]


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
            if not isinstance(raw_tickers, list):
                raw_tickers = []
            normalized = []
            for value in raw_tickers:
                text = str(value or '').upper().strip()
                if text and text not in normalized:
                    normalized.append(text)
            payload['portfolios'][portfolio_id] = normalized
        return payload
    legacy = _portfolio_payload_with_chart_slots(data, chart_slots)
    payload['chart_slots'] = _normalize_chart_slots(legacy.get('chart_slots'))
    normalized = []
    for value in legacy.get('portfolio', []):
        text = str(value or '').upper().strip()
        if text and text not in normalized:
            normalized.append(text)
    payload['portfolios'][DEFAULT_MAIN_PORTFOLIO_ID] = normalized
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
        tickers = []
        for value in raw_entry.get('tickers', raw_entry.get('portfolio', [])):
            text = str(value or '').upper().strip()
            if text and text not in tickers:
                tickers.append(text)
        tracker_data = dict(raw_entry.get('tracker_data', {})) if isinstance(raw_entry.get('tracker_data', {}), dict) else {}
        options_data = list(raw_entry.get('options_data', [])) if isinstance(raw_entry.get('options_data', []), list) else []
        portfolios[portfolio_id] = {'name': names[portfolio_id], 'tickers': tickers, 'tracker_data': tracker_data, 'options_data': options_data}
    return {
        'chart_slots': base['chart_slots'],
        'main_portfolio_id': main_portfolio_id,
        'active_portfolio_id': active_portfolio_id,
        'portfolios': portfolios,
    }


def _sanitize_chart_slots(chart_slots: Any=None) -> Any:
    """Normalize chart-slot input into the persisted 3-slot shape."""
    raw_slots = chart_slots if isinstance(chart_slots, list) else list(DEFAULT_CHART_SLOTS)
    slots = []
    for value in raw_slots:
        text = str(value or '').upper().strip()
        if text:
            slots.append(text)
    fallback = list(DEFAULT_CHART_SLOTS)
    while len(slots) < len(fallback):
        slots.append(fallback[len(slots)])
    return slots[:len(fallback)]


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
PORTFOLIO_FILE = BASE_DIR / 'portfolio.json'


def load_all_portfolios_state() -> Any:
    """Load the normalized state for all supported portfolios."""
    portfolio_storage = _normalize_portfolio_storage(_read_json(PORTFOLIO_FILE, None))
    tracker_storage = _normalize_tracker_storage(_read_json(TRACKER_FILE, None))
    options_storage = _normalize_options_storage(_read_json(OPTIONS_FILE, None))
    preferences = load_portfolio_preferences()
    state = {
        'version': MULTI_PORTFOLIO_VERSION,
        'main_portfolio_id': _normalize_main_portfolio_id(preferences.get('main_portfolio_id') or portfolio_storage.get('main_portfolio_id')),
        'active_portfolio_id': _normalize_main_portfolio_id(preferences.get('active_portfolio_id') or portfolio_storage.get('active_portfolio_id') or preferences.get('main_portfolio_id') or portfolio_storage.get('main_portfolio_id')),
        'portfolios': {},
    }
    for portfolio_id in PORTFOLIO_IDS:
        portfolio_entry = portfolio_storage['portfolios'].get(portfolio_id, _default_portfolio_entry(portfolio_id))
        tracker_entry = tracker_storage['portfolios'].get(portfolio_id, {})
        options_entry = options_storage['portfolios'].get(portfolio_id, [])
        metadata = preferences.get('portfolios', {}).get(portfolio_id, {})
        state['portfolios'][portfolio_id] = {
            'id': portfolio_id,
            'name': _normalize_portfolio_name(portfolio_id, metadata.get('name')),
            'portfolio': list(portfolio_entry.get('portfolio', [])),
            'chart_slots': _sanitize_chart_slots(portfolio_entry.get('chart_slots')),
            'portfolio_tracker': tracker_entry if isinstance(tracker_entry, dict) else {},
            'options_tracker': list(options_entry) if isinstance(options_entry, list) else [],
        }
    return state


def save_all_portfolios_state(state: Any) -> Any:
    """Persist the normalized state for all supported portfolios."""
    normalized = _normalize_multi_portfolio_state(state)
    _write_json(PORTFOLIO_FILE, _serialize_portfolio_storage(normalized), indent=2)
    _write_json(TRACKER_FILE, _serialize_tracker_storage(normalized), indent=2)
    _write_json(OPTIONS_FILE, _serialize_options_storage(normalized), indent=2)
    save_portfolio_preferences({
        'main_portfolio_id': normalized['main_portfolio_id'],
        'active_portfolio_id': normalized.get('active_portfolio_id', normalized['main_portfolio_id']),
        'portfolios': {portfolio_id: {'name': entry['name']} for portfolio_id, entry in normalized['portfolios'].items()},
    })
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
TRACKER_FILE = BASE_DIR / 'portfolio_tracker.json'

def load_tracker_data(portfolio_id: Any=None) -> Any:
    """Load tracker data."""
    return load_active_portfolio_state(portfolio_id).get('portfolio_tracker', {})

def save_tracker_data(data: Any, portfolio_id: Any=None) -> None:
    """Save tracker data."""
    state = load_all_portfolios_state()
    active_id = _normalize_main_portfolio_id(portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['portfolio_tracker'] = data if isinstance(data, dict) else {}
    save_all_portfolios_state(state)
OPTIONS_FILE = BASE_DIR / 'options_tracker.json'

def load_options_data(portfolio_id: Any=None) -> Any:
    """Load options data."""
    return load_active_portfolio_state(portfolio_id).get('options_tracker', [])

def save_options_data(data: Any, portfolio_id: Any=None) -> None:
    """Save options data."""
    state = load_all_portfolios_state()
    active_id = _normalize_main_portfolio_id(portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['options_tracker'] = list(data) if isinstance(data, list) else []
    save_all_portfolios_state(state)
NETWORTH_FILE = BASE_DIR / 'net_worth.json'

def load_networth_data() -> Any:
    """Load networth data."""
    if NETWORTH_FILE.exists():
        data = _read_json(NETWORTH_FILE, None)
        if isinstance(data, dict):
            return data
    return {'cash': [], 'debt': []}

def save_networth_data(data: Any) -> None:
    """Save networth data."""
    _write_json(NETWORTH_FILE, data, indent=2)


def build_user_data_backup() -> Any:
    """Build a single-file backup payload for all persisted user data."""
    portfolio_state = load_all_portfolios_state()
    backup = {
        'version': USER_DATA_BACKUP_VERSION,
        'exported_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'main_portfolio_id': portfolio_state['main_portfolio_id'],
        'active_portfolio_id': portfolio_state.get('active_portfolio_id', portfolio_state['main_portfolio_id']),
        'portfolios': portfolio_state['portfolios'],
        'net_worth': load_networth_data(),
    }
    return backup


def export_user_data_backup(path: Any) -> None:
    """Write the current backup payload to a single JSON file."""
    _write_json(path, build_user_data_backup(), indent=2)


def _validate_backup_payload(payload: Any) -> Any:
    """Validate imported backup data and return a normalized payload."""
    if not isinstance(payload, dict):
        raise ValueError('Backup file must contain a JSON object.')
    networth_payload = payload.get('net_worth')
    if not isinstance(networth_payload, dict):
        raise ValueError('Backup net worth data must be a JSON object.')
    if not isinstance(networth_payload.get('cash', []), list) or not isinstance(networth_payload.get('debt', []), list):
        raise ValueError('Backup net worth data must include cash and debt lists.')
    has_multi_portfolios = isinstance(payload.get('portfolios'), dict)
    has_legacy_payload = any((key in payload for key in ('portfolio', 'portfolio_tracker', 'options_tracker')))
    if not has_multi_portfolios and not has_legacy_payload:
        raise ValueError('Backup file is missing portfolio data.')
    portfolio_state = _normalize_multi_portfolio_state(payload)
    return {
        'version': MULTI_PORTFOLIO_VERSION,
        'main_portfolio_id': portfolio_state['main_portfolio_id'],
        'active_portfolio_id': portfolio_state.get('active_portfolio_id', portfolio_state['main_portfolio_id']),
        'portfolios': portfolio_state['portfolios'],
        'net_worth': {'cash': list(networth_payload.get('cash', [])), 'debt': list(networth_payload.get('debt', []))},
    }


def load_user_data_backup(path: Any) -> Any:
    """Load and validate a single-file backup payload."""
    payload = _read_json(path, None)
    if payload is None:
        raise ValueError('Unable to read backup file.')
    return _validate_backup_payload(payload)


def apply_user_data_backup(payload: Any) -> Any:
    """Persist validated backup data and return the normalized state."""
    normalized = _validate_backup_payload(payload)
    save_all_portfolios_state(normalized)
    save_networth_data(normalized['net_worth'])
    return normalized


def reset_user_data(chart_slots: Any=None) -> Any:
    """Persist a cleared user-data state while preserving chart slots."""
    normalized = {
        'main_portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID,
        'active_portfolio_id': DEFAULT_MAIN_PORTFOLIO_ID,
        'portfolios': {
            portfolio_id: _default_portfolio_entry(portfolio_id, chart_slots if portfolio_id == DEFAULT_MAIN_PORTFOLIO_ID else None) for portfolio_id in PORTFOLIO_IDS
        },
        'net_worth': {'cash': [], 'debt': []},
    }
    return apply_user_data_backup(normalized)


def load_app_config() -> Any:
    """Load app-level config data."""
    data = _read_json(APP_CONFIG_FILE, None)
    return data if isinstance(data, dict) else {}


def save_app_config(data: Any) -> None:
    """Persist app-level config data."""
    if not isinstance(data, dict):
        data = {}
    _write_json(APP_CONFIG_FILE, data, indent=2)


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


def load_chart_page_settings() -> Any:
    """Load persisted state for the dedicated Charts page."""
    config = load_app_config()
    saved = config.get('chart_page', {})
    if not isinstance(saved, dict):
        saved = {}
    symbol = str(saved.get('symbol', DEFAULT_CHART_PAGE_SETTINGS['symbol']) or DEFAULT_CHART_PAGE_SETTINGS['symbol']).upper()
    timeframe_label = str(saved.get('timeframe_label', DEFAULT_CHART_PAGE_SETTINGS['timeframe_label']) or DEFAULT_CHART_PAGE_SETTINGS['timeframe_label'])
    raw_watchlist = saved.get('watchlist', [])
    if not isinstance(raw_watchlist, list):
        raw_watchlist = []
    watchlist = []
    for symbol_value in raw_watchlist:
        text = str(symbol_value or '').upper().strip()
        if text and text not in watchlist:
            watchlist.append(text)
    raw_indicators = saved.get('indicators', DEFAULT_CHART_PAGE_SETTINGS['indicators'])
    if not isinstance(raw_indicators, list):
        raw_indicators = list(DEFAULT_CHART_PAGE_SETTINGS['indicators'])
    indicators = []
    for name in raw_indicators:
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
    if not indicators:
        indicators = list(DEFAULT_CHART_PAGE_SETTINGS['indicators'])
    auto_value = saved.get('auto', DEFAULT_CHART_PAGE_SETTINGS['auto'])
    auto_enabled = bool(auto_value) if isinstance(auto_value, bool | int) else DEFAULT_CHART_PAGE_SETTINGS['auto']
    return {'symbol': symbol, 'timeframe_label': timeframe_label, 'watchlist': watchlist, 'indicators': indicators, 'auto': auto_enabled}


def save_chart_page_settings(settings: Any) -> Any:
    """Persist state for the dedicated Charts page."""
    current = load_app_config()
    state = DEFAULT_CHART_PAGE_SETTINGS.copy()
    if isinstance(settings, dict):
        state['symbol'] = str(settings.get('symbol', state['symbol']) or state['symbol']).upper()
        state['timeframe_label'] = str(settings.get('timeframe_label', state['timeframe_label']) or state['timeframe_label'])
        raw_watchlist = settings.get('watchlist', state['watchlist'])
        if isinstance(raw_watchlist, list):
            deduped = []
            for symbol_value in raw_watchlist:
                text = str(symbol_value or '').upper().strip()
                if text and text not in deduped:
                    deduped.append(text)
            state['watchlist'] = deduped
        raw_indicators = settings.get('indicators', state['indicators'])
        if isinstance(raw_indicators, list):
            normalized = []
            for name in raw_indicators:
                text = str(name or '').strip().title()
                if text in ('Volume', 'Rsi'):
                    text = 'RSI' if text == 'Rsi' else text
                if text in ('Volume', 'RSI') and text not in normalized:
                    normalized.append(text)
            state['indicators'] = normalized or list(DEFAULT_CHART_PAGE_SETTINGS['indicators'])
        auto_value = settings.get('auto', state['auto'])
        if isinstance(auto_value, bool | int):
            state['auto'] = bool(auto_value)
    current['chart_page'] = state
    save_app_config(current)
    return state


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
