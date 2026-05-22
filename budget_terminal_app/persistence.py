from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ''}:
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from budget_terminal_app import __version__ as APP_VERSION
    from budget_terminal_app.dependencies import datetime, json, logger, math, pd
    from budget_terminal_app.paths import legacy_documents_user_data_path, user_data_path
    from budget_terminal_app.persistence_schema import USER_DATA_SCHEMA_VERSION, migrate_user_data_payload
else:
    from . import __version__ as APP_VERSION
    from .dependencies import datetime, json, logger, math, pd
    from .paths import legacy_documents_user_data_path, user_data_path
    from .persistence_schema import USER_DATA_SCHEMA_VERSION, migrate_user_data_payload

DEFAULT_CHART_SLOTS = ['AAPL', 'TSLA', 'NVDA']
USER_DATA_BACKUP_VERSION = USER_DATA_SCHEMA_VERSION
USER_DATA_FILE = user_data_path('user_data.json')
LEGACY_USER_DATA_FILE = legacy_documents_user_data_path('user_data.json')
LEGACY_DASHBOARD_LEFT_SPLITTER_FILE = user_data_path('p1_left_splitter.json')
ROLLBACK_BACKUPS_DIR = user_data_path('backups', 'rollbacks')
CORRUPT_USER_DATA_BACKUPS_DIR = user_data_path('backups', 'corrupt')
LEGACY_NOTES_IMAGES_DIR = user_data_path('notes_images')
DEFAULT_CHART_PAGE_SETTINGS = {
    'symbol': 'SPY',
    'timeframe_label': '1 Day',
    'compare_interval_label': '1 Day',
    'compare_range_label': '5Y',
    'watchlist': [],
    'compare_symbols': [],
    'compare_presets': [],
    'multi_interval_labels': [],
    'indicators': ['Volume', '200 MA'],
    'auto': True,
}
DEFAULT_FUNDAMENTALS_PAGE_SETTINGS = {
    'last_ticker': '',
    'selected_configuration': 'default',
    'custom_selections_by_ticker': {},
}
DEFAULT_DASHBOARD_CHART_SETTINGS = {
    'symbol': 'SPY',
    'timeframe_label': '1 Day',
    'indicators': ['Volume', '200 MA'],
    'auto': True,
    'splitter_sizes': [5, 2],
    'main_splitter_sizes': [3, 5],
    'left_splitter_sizes': [3, 2, 2],
}
DEFAULT_STOCKS_PAGE_SETTINGS = {
    'symbol': 'SPY',
    'auto': True,
    'mfi_enabled': False,
    'main_splitter_sizes': [3, 3, 5],
    'left_splitter_sizes': [4, 2, 3],
    'middle_splitter_sizes': [2, 2, 3],
}
DEFAULT_PORTFOLIO_METRICS_SETTINGS = {'benchmark_symbol': 'SPY', 'lookback_key': '1y'}
DEFAULT_MULTI_CHARTS_SETTINGS = {'custom_symbols': [], 'order': []}
DEFAULT_YOUTUBE_SETTINGS = {'sort_column': -1, 'sort_descending': False}
DEFAULT_THEME_SETTINGS = {'selected_theme': 'trading_dark'}
DEFAULT_OPTIONS_CHAIN_SETTINGS = {'default_risk_free_rate': 0.04}
MAX_PORTFOLIOS = 5
MULTI_PORTFOLIO_VERSION = 3
PORTFOLIO_IDS = [f'portfolio_{index}' for index in range(1, MAX_PORTFOLIOS + 1)]
DEFAULT_MAIN_PORTFOLIO_ID = PORTFOLIO_IDS[0]
DEFAULT_PORTFOLIO_NAMES = {portfolio_id: f'Portfolio {index}' for index, portfolio_id in enumerate(PORTFOLIO_IDS, start=1)}
SUPPORTED_THEME_IDS = (DEFAULT_THEME_SETTINGS['selected_theme'], 'cyberpunk_terminal')
PORTFOLIO_METRICS_LOOKBACK_CHOICES = ('1y', '3y', '5y', 'max')


def _read_json(path: Any, default: Any) -> Any:
    """Read JSON from disk, returning a fallback on failure."""
    target = Path(path)
    try:
        with target.open(encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        backup_path = _backup_unreadable_json_file(target, reason='invalid_json')
        logger.error('Unable to parse JSON from %s: %s. A backup was written to %s.', target, exc, backup_path)
    except OSError as exc:
        logger.error('Unable to read JSON from %s: %s', target, exc)
    return default


def _backup_unreadable_json_file(path: Any, *, reason: str='unreadable') -> str:
    """Copy an unreadable user-data JSON file to a timestamped backup path."""
    source = Path(path)
    if not source.exists() or not source.is_file():
        return ''
    safe_reason = ''.join(char if char.isalnum() or char in {'_', '-'} else '_' for char in str(reason or 'unreadable')).strip('_') or 'unreadable'
    backup_root = Path(CORRUPT_USER_DATA_BACKUPS_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_root / f'{source.stem}_{safe_reason}_{timestamp}{source.suffix or ".json"}'
    suffix = 2
    while backup_path.exists():
        backup_path = backup_root / f'{source.stem}_{safe_reason}_{timestamp}_{suffix}{source.suffix or ".json"}'
        suffix += 1
    try:
        shutil.copy2(source, backup_path)
    except OSError as exc:
        logger.error('Unable to create unreadable JSON backup for %s: %s', source, exc)
        return ''
    return str(backup_path)


def _write_json(path: Any, data: Any, *, indent: Any=None) -> None:
    """Write JSON data to disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
    temp_path = target.with_name(f'.{target.name}.{os.getpid()}.{timestamp}.tmp')
    try:
        with temp_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temp_path), str(target))
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            logger.debug('Unable to remove temporary JSON file %s after write failure.', temp_path)
        raise


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


def _normalize_portfolio_order(raw_order: Any, raw_portfolios: Any=None) -> Any:
    """Normalize portfolio order into a non-empty ordered subset of supported ids."""
    order = []
    if isinstance(raw_order, list):
        for value in raw_order:
            portfolio_id = _normalize_portfolio_id(value)
            if portfolio_id not in order:
                order.append(portfolio_id)
    portfolios = raw_portfolios if isinstance(raw_portfolios, dict) else {}
    for portfolio_id in portfolios.keys():
        clean_id = _normalize_portfolio_id(portfolio_id)
        if clean_id not in order:
            order.append(clean_id)
    if not order:
        order = [DEFAULT_MAIN_PORTFOLIO_ID]
    return order[:MAX_PORTFOLIOS]


def _normalize_selected_portfolio_id(value: Any, portfolio_order: Any, fallback: Any=None) -> Any:
    """Return a selected portfolio id that exists in the ordered portfolio catalog."""
    order = _normalize_portfolio_order(portfolio_order)
    fallback_id = _normalize_portfolio_id(fallback or (order[0] if order else DEFAULT_MAIN_PORTFOLIO_ID))
    portfolio_id = _normalize_portfolio_id(value)
    return portfolio_id if portfolio_id in order else fallback_id


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


def _normalize_compare_preset_name(value: Any) -> str:
    """Normalize one compare preset name without losing display casing."""
    return str(value or '').strip()


def _normalize_compare_presets(values: Any) -> list[dict[str, Any]]:
    """Normalize named compare presets into a stable persisted shape."""
    normalized = []
    seen = set()
    if not isinstance(values, list):
        return normalized
    for entry in values:
        preset = entry if isinstance(entry, dict) else {}
        name = _normalize_compare_preset_name(preset.get('name'))
        if not name:
            continue
        name_key = name.casefold()
        if name_key in seen:
            continue
        symbols = _normalize_unique_symbol_list(preset.get('symbols', []))
        if not symbols:
            continue
        interval_label = str(
            preset.get('interval_label', DEFAULT_CHART_PAGE_SETTINGS['compare_interval_label'])
            or DEFAULT_CHART_PAGE_SETTINGS['compare_interval_label']
        ).strip()
        if interval_label not in {'1 Day', '1 Week'}:
            interval_label = DEFAULT_CHART_PAGE_SETTINGS['compare_interval_label']
        range_label = str(
            preset.get('range_label', DEFAULT_CHART_PAGE_SETTINGS['compare_range_label'])
            or DEFAULT_CHART_PAGE_SETTINGS['compare_range_label']
        ).strip().upper()
        if range_label not in {'5Y', '3Y', '1Y', 'YTD', '3M', '1M'}:
            range_label = DEFAULT_CHART_PAGE_SETTINGS['compare_range_label']
        normalized.append({
            'name': name,
            'symbols': symbols,
            'interval_label': interval_label,
            'range_label': range_label,
        })
        seen.add(name_key)
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


def _normalize_cash_balance(value: Any) -> float:
    """Normalize a persisted brokerage cash balance."""
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    if not math.isfinite(amount):
        amount = 0.0
    return max(amount, 0.0)


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
            'cash_balance': _normalize_cash_balance(raw_entry.get('cash_balance')),
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
        'cash_balance': 0.0,
    }


def _normalize_portfolio_name(portfolio_id: Any, name: Any) -> Any:
    """Return a safe user-visible portfolio name."""
    text = str(name or '').strip()
    return text if text else DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, str(portfolio_id or DEFAULT_MAIN_PORTFOLIO_ID))


def _normalize_portfolio_catalog(raw_catalog: Any, portfolio_order: Any=None) -> Any:
    """Normalize metadata for the ordered set of existing portfolios."""
    catalog = {}
    source = raw_catalog if isinstance(raw_catalog, dict) else {}
    order = _normalize_portfolio_order(portfolio_order, source)
    for portfolio_id in order:
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
        'portfolio_order': [DEFAULT_MAIN_PORTFOLIO_ID],
        'portfolios': {DEFAULT_MAIN_PORTFOLIO_ID: _default_portfolio_entry(DEFAULT_MAIN_PORTFOLIO_ID, chart_slots)},
    }
    if not isinstance(payload, dict):
        return normalized
    portfolio_map = payload.get('portfolios', {})
    if not isinstance(portfolio_map, dict):
        portfolio_map = {}
    order = _normalize_portfolio_order(payload.get('portfolio_order'), payload.get('portfolio_catalog') or portfolio_map)
    metadata = _normalize_portfolio_catalog(payload.get('portfolio_catalog') or portfolio_map, order)
    normalized['portfolio_order'] = order
    normalized['main_portfolio_id'] = _normalize_selected_portfolio_id(payload.get('main_portfolio_id'), order, order[0])
    normalized['active_portfolio_id'] = _normalize_selected_portfolio_id(payload.get('active_portfolio_id', normalized['main_portfolio_id']), order, normalized['main_portfolio_id'])
    normalized['portfolios'] = {}
    for portfolio_id in order:
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
            'cash_balance': _normalize_cash_balance(raw_entry.get('cash_balance')),
        }
    if 'portfolio' in payload or 'portfolio_tracker' in payload or 'options_tracker' in payload:
        legacy_portfolio = _portfolio_payload_with_chart_slots(payload.get('portfolio', []), chart_slots)
        legacy_tracker = payload.get('portfolio_tracker', {})
        legacy_options = payload.get('options_tracker', [])
        if DEFAULT_MAIN_PORTFOLIO_ID not in normalized['portfolio_order']:
            normalized['portfolio_order'].insert(0, DEFAULT_MAIN_PORTFOLIO_ID)
        normalized['portfolios'][DEFAULT_MAIN_PORTFOLIO_ID] = {
            'id': DEFAULT_MAIN_PORTFOLIO_ID,
            'name': normalized['portfolios'].get(DEFAULT_MAIN_PORTFOLIO_ID, {}).get('name', _normalize_portfolio_name(DEFAULT_MAIN_PORTFOLIO_ID, None)),
            'portfolio': list(legacy_portfolio.get('portfolio', [])),
            'chart_slots': _sanitize_chart_slots(legacy_portfolio.get('chart_slots')),
            'portfolio_tracker': legacy_tracker if isinstance(legacy_tracker, dict) else {},
            'options_tracker': list(legacy_options) if isinstance(legacy_options, list) else [],
            'cash_balance': _normalize_cash_balance(payload.get('cash_balance')),
        }
        normalized['main_portfolio_id'] = _normalize_selected_portfolio_id(payload.get('main_portfolio_id'), normalized['portfolio_order'], DEFAULT_MAIN_PORTFOLIO_ID)
        normalized['active_portfolio_id'] = _normalize_selected_portfolio_id(payload.get('active_portfolio_id', normalized['main_portfolio_id']), normalized['portfolio_order'], normalized['main_portfolio_id'])
    return normalized


def _serialize_portfolio_storage(state: Any) -> Any:
    """Build the on-disk portfolio.json payload from normalized state."""
    normalized = _normalize_multi_portfolio_state(state)
    return {
        'version': MULTI_PORTFOLIO_VERSION,
        'main_portfolio_id': normalized['main_portfolio_id'],
        'active_portfolio_id': normalized['active_portfolio_id'],
        'portfolio_order': list(normalized.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])),
        'portfolios': {
            portfolio_id: _portfolio_payload_with_chart_slots(
                normalized.get('portfolios', {}).get(portfolio_id, {}),
                normalized.get('portfolios', {}).get(portfolio_id, {}).get('chart_slots'),
            ) for portfolio_id in normalized.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])
        },
    }


def _serialize_tracker_storage(state: Any) -> Any:
    """Build the on-disk portfolio_tracker.json payload from normalized state."""
    normalized = _normalize_multi_portfolio_state(state)
    return {
        'version': MULTI_PORTFOLIO_VERSION,
        'portfolio_order': list(normalized.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])),
        'portfolios': {
            portfolio_id: dict(normalized.get('portfolios', {}).get(portfolio_id, {}).get('portfolio_tracker', {})) for portfolio_id in normalized.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])
        },
    }


def _serialize_options_storage(state: Any) -> Any:
    """Build the on-disk options_tracker.json payload from normalized state."""
    normalized = _normalize_multi_portfolio_state(state)
    return {
        'version': MULTI_PORTFOLIO_VERSION,
        'portfolio_order': list(normalized.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])),
        'portfolios': {
            portfolio_id: list(normalized.get('portfolios', {}).get(portfolio_id, {}).get('options_tracker', [])) for portfolio_id in normalized.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])
        },
    }


def _normalize_networth_payload(data: Any) -> Any:
    """Normalize persisted net-worth lists into the supported shape."""
    payload = data if isinstance(data, dict) else {}
    cash = payload.get('cash', [])
    debt = payload.get('debt', [])
    recurring_bills_payload = payload.get('recurring_bills', [])
    recurring_bills = []
    if isinstance(recurring_bills_payload, list):
        for item in recurring_bills_payload:
            bill = item if isinstance(item, dict) else {}
            desc = str(bill.get('desc', bill.get('description', 'Recurring Bill')) or 'Recurring Bill').strip()[:80] or 'Recurring Bill'
            try:
                amount = float(bill.get('amount', 0.0) or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            if not math.isfinite(amount):
                amount = 0.0
            frequency = str(bill.get('frequency', 'monthly') or 'monthly').strip().lower()
            if frequency not in ('monthly', 'yearly'):
                frequency = 'monthly'
            currency = str(bill.get('currency', 'SGD') or 'SGD').upper().strip()
            if currency not in ('SGD', 'USD'):
                currency = 'SGD'
            recurring_bills.append({
                'desc': desc,
                'amount': max(amount, 0.0),
                'frequency': frequency,
                'currency': currency,
            })
    totals_currency = str(payload.get('totals_currency', 'SGD') or 'SGD').upper().strip()
    if totals_currency not in ('SGD', 'USD'):
        totals_currency = 'SGD'
    goal_payload = payload.get('goal', {})
    goal = goal_payload if isinstance(goal_payload, dict) else {}
    goal_title = str(goal.get('title', 'Net Worth Goal') or 'Net Worth Goal').strip()[:64] or 'Net Worth Goal'
    goal_currency = str(goal.get('currency', totals_currency) or totals_currency).upper().strip()
    if goal_currency not in ('SGD', 'USD'):
        goal_currency = totals_currency
    try:
        goal_target = float(goal.get('target_amount', 0.0) or 0.0)
    except (TypeError, ValueError):
        goal_target = 0.0
    if not math.isfinite(goal_target):
        goal_target = 0.0
    return {
        'cash': list(cash) if isinstance(cash, list) else [],
        'debt': list(debt) if isinstance(debt, list) else [],
        'recurring_bills': recurring_bills,
        'totals_currency': totals_currency,
        'goal': {
            'title': goal_title,
            'target_amount': max(goal_target, 0.0),
            'currency': goal_currency,
        },
    }


def default_networth_data() -> Any:
    """Return a normalized empty Personal Finance payload."""
    return _normalize_networth_payload({})


def normalize_networth_data(data: Any) -> Any:
    """Return a normalized Personal Finance payload for runtime use."""
    return _normalize_networth_payload(data)


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


def _clear_legacy_notes_storage() -> None:
    """Remove leftover note storage from versions that still shipped the Notes page."""
    legacy_path = Path(LEGACY_NOTES_IMAGES_DIR)
    if not legacy_path.exists():
        return
    try:
        if legacy_path.is_dir():
            shutil.rmtree(legacy_path, ignore_errors=True)
        else:
            legacy_path.unlink(missing_ok=True)
    except OSError:
        logger.warning('Unable to remove legacy notes storage at %s.', legacy_path)

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
        'portfolio_order': list(portfolio_state.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])),
        'portfolios': portfolio_state['portfolios'],
        'fundamentals_page': _normalize_fundamentals_page_settings(DEFAULT_FUNDAMENTALS_PAGE_SETTINGS),
        'chart_page': DEFAULT_CHART_PAGE_SETTINGS.copy(),
        'dashboard_chart': DEFAULT_DASHBOARD_CHART_SETTINGS.copy(),
        'stocks_page': DEFAULT_STOCKS_PAGE_SETTINGS.copy(),
        'portfolio_metrics': DEFAULT_PORTFOLIO_METRICS_SETTINGS.copy(),
        'multi_charts': DEFAULT_MULTI_CHARTS_SETTINGS.copy(),
        'youtube': DEFAULT_YOUTUBE_SETTINGS.copy(),
        'net_worth': default_networth_data(),
        'theme': DEFAULT_THEME_SETTINGS.copy(),
        'options_chain': DEFAULT_OPTIONS_CHAIN_SETTINGS.copy(),
        'time_12h': False,
    }


def _normalize_user_data_document(payload: Any) -> Any:
    """Normalize persisted single-file user data into the canonical shape."""
    default = _default_user_data_document()
    original_saved = payload if isinstance(payload, dict) else {}
    migration = migrate_user_data_payload(payload, default)
    saved = migration.payload if isinstance(migration.payload, dict) else {}
    portfolio_state = _normalize_multi_portfolio_state(saved)
    chart_page_payload = saved.get('chart_page', default['chart_page'])
    saved_dashboard_chart_payload = saved.get('dashboard_chart')
    dashboard_chart_payload = saved_dashboard_chart_payload if isinstance(saved_dashboard_chart_payload, dict) else default['dashboard_chart']
    original_dashboard_chart_payload = original_saved.get('dashboard_chart')
    if not isinstance(original_dashboard_chart_payload, dict) or 'left_splitter_sizes' not in original_dashboard_chart_payload:
        legacy_left_splitter_sizes = _load_legacy_dashboard_left_splitter_sizes()
        if legacy_left_splitter_sizes is not None:
            dashboard_chart_payload = dict(dashboard_chart_payload)
            dashboard_chart_payload['left_splitter_sizes'] = legacy_left_splitter_sizes
    exported_compare_presets = saved.get('compare_presets')
    if isinstance(exported_compare_presets, list):
        chart_page_payload = dict(chart_page_payload) if isinstance(chart_page_payload, dict) else {}
        chart_page_payload['compare_presets'] = exported_compare_presets
    return {
        'version': USER_DATA_BACKUP_VERSION,
        'main_portfolio_id': portfolio_state['main_portfolio_id'],
        'active_portfolio_id': portfolio_state.get('active_portfolio_id', portfolio_state['main_portfolio_id']),
        'portfolio_order': list(portfolio_state.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID])),
        'portfolios': portfolio_state['portfolios'],
        'fundamentals_page': _normalize_fundamentals_page_settings(saved.get('fundamentals_page', default['fundamentals_page'])),
        'chart_page': _normalize_chart_page_settings(chart_page_payload),
        'dashboard_chart': _normalize_dashboard_chart_settings(dashboard_chart_payload),
        'stocks_page': _normalize_stocks_page_settings(saved.get('stocks_page', default['stocks_page'])),
        'portfolio_metrics': _normalize_portfolio_metrics_settings(saved.get('portfolio_metrics', default['portfolio_metrics'])),
        'multi_charts': _normalize_multi_charts_settings(saved.get('multi_charts', default['multi_charts'])),
        'youtube': _normalize_youtube_settings(saved.get('youtube', default['youtube'])),
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
    _clear_legacy_notes_storage()
    return normalized


def _load_user_data_document() -> Any:
    """Load the current single-file user-data document from LocalAppData."""
    migrated = _migrate_legacy_user_data_file()
    if migrated is not None:
        return migrated
    raw_document = _read_json(USER_DATA_FILE, None)
    normalized = _normalize_user_data_document(raw_document)
    if (isinstance(raw_document, dict) and 'notes' in raw_document) or Path(LEGACY_NOTES_IMAGES_DIR).exists():
        _write_json(USER_DATA_FILE, normalized, indent=2)
        _clear_legacy_notes_storage()
    return normalized


def _save_user_data_document(data: Any) -> Any:
    """Persist the normalized single-file user-data document to LocalAppData."""
    normalized = _normalize_user_data_document(data)
    _write_json(USER_DATA_FILE, normalized, indent=2)
    _clear_legacy_notes_storage()
    return normalized


def load_all_portfolios_state() -> Any:
    """Load the normalized state for all supported portfolios."""
    document = _load_user_data_document()
    return _normalize_multi_portfolio_state(document)


def save_all_portfolios_state(state: Any) -> Any:
    """Persist the normalized state for all supported portfolios."""
    normalized = _normalize_multi_portfolio_state(state)
    document = _load_user_data_document()
    document['main_portfolio_id'] = normalized['main_portfolio_id']
    document['active_portfolio_id'] = normalized.get('active_portfolio_id', normalized['main_portfolio_id'])
    document['portfolio_order'] = list(normalized.get('portfolio_order', [DEFAULT_MAIN_PORTFOLIO_ID]))
    document['portfolios'] = normalized['portfolios']
    _save_user_data_document(document)
    return normalized


def _resolve_state_portfolio_id(state: Any, portfolio_id: Any=None) -> Any:
    """Return an existing portfolio id from normalized state."""
    order = _normalize_portfolio_order(state.get('portfolio_order'), state.get('portfolios', {})) if isinstance(state, dict) else [DEFAULT_MAIN_PORTFOLIO_ID]
    fallback = state.get('active_portfolio_id') if isinstance(state, dict) else DEFAULT_MAIN_PORTFOLIO_ID
    return _normalize_selected_portfolio_id(portfolio_id or fallback or DEFAULT_MAIN_PORTFOLIO_ID, order, order[0])


def load_active_portfolio_state(portfolio_id: Any=None) -> Any:
    """Load one normalized portfolio state."""
    state = load_all_portfolios_state()
    active_id = _resolve_state_portfolio_id(state, portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    active = state['portfolios'][active_id]
    return {
        'main_portfolio_id': state.get('main_portfolio_id', active_id),
        'portfolio_id': active_id,
        'portfolio_name': active.get('name', DEFAULT_PORTFOLIO_NAMES.get(active_id, active_id)),
        'portfolio': list(active.get('portfolio', [])),
        'chart_slots': _sanitize_chart_slots(active.get('chart_slots')),
        'portfolio_tracker': dict(active.get('portfolio_tracker', {})),
        'options_tracker': list(active.get('options_tracker', [])),
        'cash_balance': _normalize_cash_balance(active.get('cash_balance')),
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
    active_id = _resolve_state_portfolio_id(state, portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['portfolio'] = list(portfolio) if isinstance(portfolio, list) else []
    state['portfolios'][active_id]['chart_slots'] = _sanitize_chart_slots(chart_slots if chart_slots is not None else state['portfolios'][active_id].get('chart_slots'))
    save_all_portfolios_state(state)

def load_tracker_data(portfolio_id: Any=None) -> Any:
    """Load tracker data."""
    return load_active_portfolio_state(portfolio_id).get('portfolio_tracker', {})

def save_tracker_data(data: Any, portfolio_id: Any=None) -> None:
    """Save tracker data."""
    state = load_all_portfolios_state()
    active_id = _resolve_state_portfolio_id(state, portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['portfolio_tracker'] = data if isinstance(data, dict) else {}
    save_all_portfolios_state(state)

def load_options_data(portfolio_id: Any=None) -> Any:
    """Load options data."""
    return load_active_portfolio_state(portfolio_id).get('options_tracker', [])

def save_options_data(data: Any, portfolio_id: Any=None) -> None:
    """Save options data."""
    state = load_all_portfolios_state()
    active_id = _resolve_state_portfolio_id(state, portfolio_id or state.get('active_portfolio_id') or state['main_portfolio_id'])
    state['portfolios'][active_id]['options_tracker'] = list(data) if isinstance(data, list) else []
    save_all_portfolios_state(state)

def load_networth_data() -> Any:
    """Load networth data."""
    return normalize_networth_data(_load_user_data_document().get('net_worth'))

def save_networth_data(data: Any) -> None:
    """Save networth data."""
    document = _load_user_data_document()
    document['net_worth'] = normalize_networth_data(data)
    _save_user_data_document(document)


def build_user_data_backup() -> Any:
    """Build a single-file backup payload for all persisted user data."""
    backup = _load_user_data_document()
    backup['compare_presets'] = list(
        _normalize_chart_page_settings(backup.get('chart_page', DEFAULT_CHART_PAGE_SETTINGS)).get('compare_presets', [])
    )
    backup['version'] = USER_DATA_BACKUP_VERSION
    backup['app_version'] = APP_VERSION
    backup['exported_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return backup


def export_user_data_backup(path: Any) -> None:
    """Write the current backup payload to a single JSON file."""
    _write_json(path, build_user_data_backup(), indent=2)


def _backup_file_path(parent_directory: Any, *, prefix: str='budget_terminal_backup') -> Path:
    """Create a unique timestamped JSON backup path within the requested parent."""
    target_root = Path(parent_directory)
    target_root.mkdir(parents=True, exist_ok=True)
    base_name = f"{prefix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_path = target_root / f'{base_name}.json'
    suffix = 2
    while backup_path.exists():
        backup_path = target_root / f'{base_name}_{suffix}.json'
        suffix += 1
    return backup_path


def create_rollback_backup_file(*, reason: str='before_import') -> str:
    """Create an automatic rollback JSON backup under local app data."""
    safe_reason = ''.join(char if char.isalnum() or char in {'_', '-'} else '_' for char in str(reason or 'before_import')).strip('_') or 'before_import'
    backup_path = _backup_file_path(ROLLBACK_BACKUPS_DIR, prefix=f'rollback_{safe_reason}')
    export_user_data_backup(backup_path)
    return str(backup_path)


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
    portfolio_order = _normalize_portfolio_order(payload.get('portfolio_order'), portfolios)
    for portfolio_id in portfolio_order:
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
        '## Compare Presets',
        '',
        _json_block(payload.get('compare_presets', payload.get('chart_page', {}).get('compare_presets', []))),
        '',
        '## Dashboard Chart Settings',
        '',
        _json_block(payload.get('dashboard_chart', DEFAULT_DASHBOARD_CHART_SETTINGS)),
        '',
        '## Stocks Page Settings',
        '',
        _json_block(payload.get('stocks_page', DEFAULT_STOCKS_PAGE_SETTINGS)),
        '',
        '## Portfolio Metrics Settings',
        '',
        _json_block(payload.get('portfolio_metrics', DEFAULT_PORTFOLIO_METRICS_SETTINGS)),
        '',
        '## Multi Charts Settings',
        '',
        _json_block(payload.get('multi_charts', DEFAULT_MULTI_CHARTS_SETTINGS)),
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
    payload = migrate_user_data_payload(payload, _default_user_data_document(), strict_future=True).payload
    has_multi_portfolios = isinstance(payload.get('portfolios'), dict)
    has_legacy_payload = any((key in payload for key in ('portfolio', 'portfolio_tracker', 'options_tracker')))
    if not has_multi_portfolios and not has_legacy_payload:
        raise ValueError('Backup file is missing portfolio data.')
    if 'net_worth' in payload:
        networth_payload = payload.get('net_worth')
        if not isinstance(networth_payload, dict):
            raise ValueError('Backup net worth data must be a JSON object.')
        if not isinstance(networth_payload.get('cash', []), list) or not isinstance(networth_payload.get('debt', []), list):
            raise ValueError('Backup net worth data must include cash and debt lists.')
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
        'portfolio_order': [DEFAULT_MAIN_PORTFOLIO_ID],
        'portfolios': {
            DEFAULT_MAIN_PORTFOLIO_ID: _default_portfolio_entry(DEFAULT_MAIN_PORTFOLIO_ID, chart_slots)
        },
        'fundamentals_page': _normalize_fundamentals_page_settings(DEFAULT_FUNDAMENTALS_PAGE_SETTINGS),
        'chart_page': DEFAULT_CHART_PAGE_SETTINGS.copy(),
        'dashboard_chart': DEFAULT_DASHBOARD_CHART_SETTINGS.copy(),
        'stocks_page': DEFAULT_STOCKS_PAGE_SETTINGS.copy(),
        'portfolio_metrics': DEFAULT_PORTFOLIO_METRICS_SETTINGS.copy(),
        'multi_charts': DEFAULT_MULTI_CHARTS_SETTINGS.copy(),
        'youtube': DEFAULT_YOUTUBE_SETTINGS.copy(),
        'net_worth': default_networth_data(),
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
            'portfolio_order': list(document.get('portfolio_order', [document['main_portfolio_id']])),
            'portfolios': {portfolio_id: {'name': entry.get('name')} for portfolio_id, entry in document.get('portfolios', {}).items()},
        },
        'theme': dict(document.get('theme', DEFAULT_THEME_SETTINGS)),
        'fundamentals_page': dict(document.get('fundamentals_page', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS)),
        'chart_page': dict(document.get('chart_page', DEFAULT_CHART_PAGE_SETTINGS)),
        'dashboard_chart': dict(document.get('dashboard_chart', DEFAULT_DASHBOARD_CHART_SETTINGS)),
        'stocks_page': dict(document.get('stocks_page', DEFAULT_STOCKS_PAGE_SETTINGS)),
        'portfolio_metrics': dict(document.get('portfolio_metrics', DEFAULT_PORTFOLIO_METRICS_SETTINGS)),
        'multi_charts': dict(document.get('multi_charts', DEFAULT_MULTI_CHARTS_SETTINGS)),
        'youtube': dict(document.get('youtube', DEFAULT_YOUTUBE_SETTINGS)),
        'options_chain': dict(document.get('options_chain', DEFAULT_OPTIONS_CHAIN_SETTINGS)),
        'time_12h': bool(document.get('time_12h', False)),
    }


def save_app_config(data: Any) -> None:
    """Persist app-level config data."""
    current = _load_user_data_document()
    saved = data if isinstance(data, dict) else {}
    portfolio_state = saved.get('portfolio_state', {})
    if isinstance(portfolio_state, dict):
        order = _normalize_portfolio_order(
            portfolio_state.get('portfolio_order'),
            portfolio_state.get('portfolios', current.get('portfolios', {})),
        )
        current['portfolio_order'] = list(order)
        current['main_portfolio_id'] = _normalize_selected_portfolio_id(portfolio_state.get('main_portfolio_id', current['main_portfolio_id']), order, order[0])
        current['active_portfolio_id'] = _normalize_selected_portfolio_id(
            portfolio_state.get('active_portfolio_id', current.get('active_portfolio_id', current['main_portfolio_id'])),
            order,
            current['main_portfolio_id'],
        )
        names = _normalize_portfolio_catalog(portfolio_state.get('portfolios'), order)
        portfolio_map = current.get('portfolios', {})
        current['portfolios'] = {}
        for portfolio_id in order:
            entry = portfolio_map.get(portfolio_id, _default_portfolio_entry(portfolio_id))
            if not isinstance(entry, dict):
                entry = _default_portfolio_entry(portfolio_id)
            entry['name'] = names.get(portfolio_id, {}).get('name', entry.get('name'))
            current['portfolios'][portfolio_id] = entry
    if 'theme' in saved:
        current['theme'] = _normalize_theme_payload(saved.get('theme'))
    if 'fundamentals_page' in saved:
        current['fundamentals_page'] = _normalize_fundamentals_page_settings(saved.get('fundamentals_page'))
    if 'chart_page' in saved:
        current['chart_page'] = _normalize_chart_page_settings(saved.get('chart_page'))
    if 'dashboard_chart' in saved:
        current['dashboard_chart'] = _normalize_dashboard_chart_settings(saved.get('dashboard_chart'))
    if 'stocks_page' in saved:
        current['stocks_page'] = _normalize_stocks_page_settings(saved.get('stocks_page'))
    if 'portfolio_metrics' in saved:
        current['portfolio_metrics'] = _normalize_portfolio_metrics_settings(saved.get('portfolio_metrics'))
    if 'multi_charts' in saved:
        current['multi_charts'] = _normalize_multi_charts_settings(saved.get('multi_charts'))
    if 'youtube' in saved:
        current['youtube'] = _normalize_youtube_settings(saved.get('youtube'))
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
    compare_interval_label = str(saved.get('compare_interval_label', DEFAULT_CHART_PAGE_SETTINGS['compare_interval_label']) or DEFAULT_CHART_PAGE_SETTINGS['compare_interval_label']).strip()
    if compare_interval_label not in {'1 Day', '1 Week'}:
        compare_interval_label = DEFAULT_CHART_PAGE_SETTINGS['compare_interval_label']
    compare_range_label = str(saved.get('compare_range_label', DEFAULT_CHART_PAGE_SETTINGS['compare_range_label']) or DEFAULT_CHART_PAGE_SETTINGS['compare_range_label']).strip().upper()
    if compare_range_label not in {'5Y', '3Y', '1Y', 'YTD', '3M', '1M'}:
        compare_range_label = DEFAULT_CHART_PAGE_SETTINGS['compare_range_label']
    raw_watchlist = saved.get('watchlist', [])
    if not isinstance(raw_watchlist, list):
        raw_watchlist = []
    watchlist = _normalize_unique_symbol_list(raw_watchlist)
    raw_compare_symbols = saved.get('compare_symbols', [])
    if not isinstance(raw_compare_symbols, list):
        raw_compare_symbols = []
    compare_symbols = _normalize_unique_symbol_list(raw_compare_symbols)
    compare_presets = _normalize_compare_presets(saved.get('compare_presets', []))
    raw_multi_interval_labels = saved.get('multi_interval_labels', [])
    if not isinstance(raw_multi_interval_labels, list):
        raw_multi_interval_labels = []
    multi_interval_labels = []
    valid_multi_interval_labels = {'1 Minute', '5 Minutes', '15 Minutes', '1 Hour', '1 Day', '1 Week', '1 Month'}
    for value in raw_multi_interval_labels:
        label = str(value or '').strip()
        if label in valid_multi_interval_labels and label not in multi_interval_labels:
            multi_interval_labels.append(label)
    indicators = _normalize_indicator_list(saved.get('indicators'), DEFAULT_CHART_PAGE_SETTINGS['indicators'])
    auto_value = saved.get('auto', DEFAULT_CHART_PAGE_SETTINGS['auto'])
    auto_enabled = bool(auto_value) if isinstance(auto_value, bool | int) else DEFAULT_CHART_PAGE_SETTINGS['auto']
    return {
        'symbol': symbol,
        'timeframe_label': timeframe_label,
        'compare_interval_label': compare_interval_label,
        'compare_range_label': compare_range_label,
        'watchlist': watchlist,
        'compare_symbols': compare_symbols,
        'compare_presets': compare_presets,
        'multi_interval_labels': multi_interval_labels,
        'indicators': indicators,
        'auto': auto_enabled,
    }


def _normalize_fundamentals_selection_rows(values: Any) -> list[str]:
    """Normalize one ordered Fundamentals row-selection list."""
    rows = []
    if not isinstance(values, list):
        return rows
    for value in values:
        row = str(value or '').strip()
        if row and row not in rows:
            rows.append(row)
    return rows


def _normalize_fundamentals_custom_selections(values: Any, *, last_ticker: str='', legacy_custom_panels: Any=None) -> dict[str, dict[str, list[str]]]:
    """Normalize per-ticker Fundamentals checklist selections, with migration support."""
    normalized = {}
    raw = values if isinstance(values, dict) else {}
    for ticker_key, selection in raw.items():
        ticker = str(ticker_key or '').upper().strip()
        if not ticker or not isinstance(selection, dict):
            continue
        family_map = {
            'financials': _normalize_fundamentals_selection_rows(selection.get('financials', [])),
            'cashflow': _normalize_fundamentals_selection_rows(selection.get('cashflow', [])),
            'balance_sheet': _normalize_fundamentals_selection_rows(selection.get('balance_sheet', [])),
        }
        if any(family_map.values()):
            normalized[ticker] = family_map
    if normalized:
        return normalized
    ticker = str(last_ticker or '').upper().strip()
    if not ticker or not isinstance(legacy_custom_panels, list):
        return {}
    migrated = {
        'financials': [],
        'cashflow': [],
        'balance_sheet': [],
    }
    for entry in legacy_custom_panels:
        panel = entry if isinstance(entry, dict) else {}
        if str(panel.get('source', '') or '').strip().lower() != 'statement_row':
            continue
        family = str(panel.get('statement_family', 'financials') or 'financials').strip().lower()
        if family not in migrated:
            continue
        row = str(panel.get('statement_row', '') or '').strip()
        if row and row not in migrated[family]:
            migrated[family].append(row)
    return {ticker: migrated} if any(migrated.values()) else {}


def _normalize_fundamentals_page_settings(settings: Any) -> dict[str, Any]:
    """Normalize persisted state for the Fundamentals page."""
    saved = settings if isinstance(settings, dict) else {}
    last_ticker = str(saved.get('last_ticker', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['last_ticker']) or '').upper().strip()
    selected_configuration = str(
        saved.get('selected_configuration', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration'])
        or DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
    ).strip().lower()
    if selected_configuration not in {'default', 'custom'}:
        selected_configuration = DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['selected_configuration']
    return {
        'last_ticker': last_ticker,
        'selected_configuration': selected_configuration,
        'custom_selections_by_ticker': _normalize_fundamentals_custom_selections(
            saved.get('custom_selections_by_ticker', DEFAULT_FUNDAMENTALS_PAGE_SETTINGS['custom_selections_by_ticker']),
            last_ticker=last_ticker,
            legacy_custom_panels=saved.get('custom_panels'),
        ),
    }


def _normalize_stocks_page_settings(settings: Any) -> Any:
    """Normalize persisted state for the Stocks page."""
    saved = settings if isinstance(settings, dict) else {}
    symbol = str(saved.get('symbol', DEFAULT_STOCKS_PAGE_SETTINGS['symbol']) or DEFAULT_STOCKS_PAGE_SETTINGS['symbol']).upper().strip()
    auto_value = saved.get('auto', DEFAULT_STOCKS_PAGE_SETTINGS['auto'])
    auto_enabled = bool(auto_value) if isinstance(auto_value, bool | int) else DEFAULT_STOCKS_PAGE_SETTINGS['auto']
    mfi_value = saved.get('mfi_enabled', DEFAULT_STOCKS_PAGE_SETTINGS['mfi_enabled'])
    mfi_enabled = bool(mfi_value) if isinstance(mfi_value, bool | int) else DEFAULT_STOCKS_PAGE_SETTINGS['mfi_enabled']
    raw_main_splitter = saved.get('main_splitter_sizes', DEFAULT_STOCKS_PAGE_SETTINGS['main_splitter_sizes'])
    main_splitter_sizes = []
    if isinstance(raw_main_splitter, list):
        for value in raw_main_splitter[:3]:
            try:
                size = max(int(value), 1)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                main_splitter_sizes.append(size)
    if len(main_splitter_sizes) != 3:
        main_splitter_sizes = list(DEFAULT_STOCKS_PAGE_SETTINGS['main_splitter_sizes'])

    raw_left_splitter = saved.get('left_splitter_sizes', DEFAULT_STOCKS_PAGE_SETTINGS['left_splitter_sizes'])
    left_splitter_sizes = []
    if isinstance(raw_left_splitter, list):
        for value in raw_left_splitter[:3]:
            try:
                size = max(int(value), 1)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                left_splitter_sizes.append(size)
    if len(left_splitter_sizes) != 3:
        left_splitter_sizes = list(DEFAULT_STOCKS_PAGE_SETTINGS['left_splitter_sizes'])

    raw_middle_splitter = saved.get('middle_splitter_sizes', DEFAULT_STOCKS_PAGE_SETTINGS['middle_splitter_sizes'])
    middle_splitter_sizes = []
    if isinstance(raw_middle_splitter, list):
        for value in raw_middle_splitter[:3]:
            try:
                size = max(int(value), 1)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                middle_splitter_sizes.append(size)
    if len(middle_splitter_sizes) == 2:
        news_size, detail_size = middle_splitter_sizes
        holder_size = max(int(detail_size * 0.4), 1)
        insider_size = max(detail_size - holder_size, 1)
        middle_splitter_sizes = [news_size, holder_size, insider_size]
    if len(middle_splitter_sizes) != 3:
        middle_splitter_sizes = list(DEFAULT_STOCKS_PAGE_SETTINGS['middle_splitter_sizes'])

    return {
        'symbol': symbol or DEFAULT_STOCKS_PAGE_SETTINGS['symbol'],
        'auto': auto_enabled,
        'mfi_enabled': mfi_enabled,
        'main_splitter_sizes': main_splitter_sizes,
        'left_splitter_sizes': left_splitter_sizes,
        'middle_splitter_sizes': middle_splitter_sizes,
    }


def _normalize_portfolio_metrics_settings(settings: Any) -> Any:
    """Normalize persisted state for the Portfolio Metrics sub-tab."""
    saved = settings if isinstance(settings, dict) else {}
    benchmark_symbol = str(
        saved.get('benchmark_symbol', DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'])
        or DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol']
    ).upper().strip()
    lookback_key = str(
        saved.get('lookback_key', DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key'])
        or DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']
    ).strip().lower()
    if lookback_key not in PORTFOLIO_METRICS_LOOKBACK_CHOICES:
        lookback_key = DEFAULT_PORTFOLIO_METRICS_SETTINGS['lookback_key']
    return {
        'benchmark_symbol': benchmark_symbol or DEFAULT_PORTFOLIO_METRICS_SETTINGS['benchmark_symbol'],
        'lookback_key': lookback_key,
    }


def _normalize_multi_charts_settings(settings: Any) -> Any:
    """Normalize persisted state for the Multi Charts page."""
    saved = settings if isinstance(settings, dict) else {}
    return {
        'custom_symbols': _normalize_unique_symbol_list(saved.get('custom_symbols', DEFAULT_MULTI_CHARTS_SETTINGS['custom_symbols'])),
        'order': _normalize_unique_symbol_list(saved.get('order', DEFAULT_MULTI_CHARTS_SETTINGS['order'])),
    }


def _normalize_youtube_settings(settings: Any) -> Any:
    """Normalize persisted state for the YouTube page."""
    saved = settings if isinstance(settings, dict) else {}
    try:
        sort_column = int(saved.get('sort_column', DEFAULT_YOUTUBE_SETTINGS['sort_column']))
    except (TypeError, ValueError):
        sort_column = DEFAULT_YOUTUBE_SETTINGS['sort_column']
    if sort_column < -1 or sort_column > 6:
        sort_column = DEFAULT_YOUTUBE_SETTINGS['sort_column']
    descending_value = saved.get('sort_descending', DEFAULT_YOUTUBE_SETTINGS['sort_descending'])
    sort_descending = bool(descending_value) if isinstance(descending_value, bool | int) else DEFAULT_YOUTUBE_SETTINGS['sort_descending']
    return {
        'sort_column': sort_column,
        'sort_descending': sort_descending,
    }


def _normalize_splitter_sizes(raw_sizes: Any, default_sizes: Any, expected_count: int) -> Any:
    """Normalize persisted QSplitter sizes into a fixed positive integer list."""
    sizes = []
    if isinstance(raw_sizes, list):
        for value in raw_sizes[:expected_count]:
            try:
                size = max(int(value), 1)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                sizes.append(size)
    if len(sizes) != expected_count:
        return list(default_sizes)
    return sizes


def _load_legacy_dashboard_left_splitter_sizes() -> Any:
    """Read the old dashboard left-column splitter file for one-time migration."""
    if not Path(LEGACY_DASHBOARD_LEFT_SPLITTER_FILE).exists():
        return None
    sizes = _normalize_splitter_sizes(
        _read_json(LEGACY_DASHBOARD_LEFT_SPLITTER_FILE, None),
        DEFAULT_DASHBOARD_CHART_SETTINGS['left_splitter_sizes'],
        3,
    )
    return sizes


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
    splitter_sizes = _normalize_splitter_sizes(
        saved.get('splitter_sizes'),
        DEFAULT_DASHBOARD_CHART_SETTINGS['splitter_sizes'],
        2,
    )
    main_splitter_sizes = _normalize_splitter_sizes(
        saved.get('main_splitter_sizes'),
        DEFAULT_DASHBOARD_CHART_SETTINGS['main_splitter_sizes'],
        2,
    )
    left_splitter_sizes = _normalize_splitter_sizes(
        saved.get('left_splitter_sizes'),
        DEFAULT_DASHBOARD_CHART_SETTINGS['left_splitter_sizes'],
        3,
    )
    return {
        'symbol': symbol or DEFAULT_DASHBOARD_CHART_SETTINGS['symbol'],
        'timeframe_label': timeframe_label or DEFAULT_DASHBOARD_CHART_SETTINGS['timeframe_label'],
        'indicators': indicators,
        'auto': auto_enabled,
        'splitter_sizes': splitter_sizes,
        'main_splitter_sizes': main_splitter_sizes,
        'left_splitter_sizes': left_splitter_sizes,
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
    order = _normalize_portfolio_order(saved.get('portfolio_order'), saved.get('portfolios'))
    catalog = _normalize_portfolio_catalog(saved.get('portfolios'), order)
    main_portfolio_id = _normalize_selected_portfolio_id(saved.get('main_portfolio_id'), order, order[0])
    active_portfolio_id = _normalize_selected_portfolio_id(saved.get('active_portfolio_id', main_portfolio_id), order, main_portfolio_id)
    return {'main_portfolio_id': main_portfolio_id, 'active_portfolio_id': active_portfolio_id, 'portfolio_order': order, 'portfolios': catalog}


def save_portfolio_preferences(settings: Any) -> Any:
    """Persist portfolio metadata and selected main/active portfolio ids in app config."""
    current = load_app_config()
    state = load_portfolio_preferences()
    if isinstance(settings, dict):
        order = _normalize_portfolio_order(settings.get('portfolio_order', state.get('portfolio_order')), settings.get('portfolios', state['portfolios']))
        state['portfolio_order'] = order
        state['main_portfolio_id'] = _normalize_selected_portfolio_id(settings.get('main_portfolio_id', state['main_portfolio_id']), order, order[0])
        state['active_portfolio_id'] = _normalize_selected_portfolio_id(settings.get('active_portfolio_id', state.get('active_portfolio_id', state['main_portfolio_id'])), order, state['main_portfolio_id'])
        state['portfolios'] = _normalize_portfolio_catalog(settings.get('portfolios', state['portfolios']), order)
    current['portfolio_state'] = {
        'main_portfolio_id': state['main_portfolio_id'],
        'active_portfolio_id': state['active_portfolio_id'],
        'portfolio_order': list(state.get('portfolio_order', [state['main_portfolio_id']])),
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


def load_fundamentals_page_settings() -> Any:
    """Load persisted state for the Fundamentals page."""
    config = load_app_config()
    return _normalize_fundamentals_page_settings(config.get('fundamentals_page', {}))


def save_fundamentals_page_settings(settings: Any) -> Any:
    """Persist state for the Fundamentals page."""
    current = load_app_config()
    state = _normalize_fundamentals_page_settings(settings)
    current['fundamentals_page'] = state
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


def load_stocks_page_settings() -> Any:
    """Load persisted state for the Stocks page."""
    config = load_app_config()
    return _normalize_stocks_page_settings(config.get('stocks_page', {}))


def save_stocks_page_settings(settings: Any) -> Any:
    """Persist state for the Stocks page."""
    current = load_app_config()
    state = _normalize_stocks_page_settings(settings)
    current['stocks_page'] = state
    save_app_config(current)
    return state


def load_portfolio_metrics_settings() -> Any:
    """Load persisted state for the Portfolio Metrics sub-tab."""
    config = load_app_config()
    return _normalize_portfolio_metrics_settings(config.get('portfolio_metrics', {}))


def save_portfolio_metrics_settings(settings: Any) -> Any:
    """Persist state for the Portfolio Metrics sub-tab."""
    current = load_app_config()
    state = _normalize_portfolio_metrics_settings(settings)
    current['portfolio_metrics'] = state
    save_app_config(current)
    return state


def load_multi_charts_settings() -> Any:
    """Load persisted state for the Multi Charts page."""
    config = load_app_config()
    return _normalize_multi_charts_settings(config.get('multi_charts', {}))


def save_multi_charts_settings(settings: Any) -> Any:
    """Persist state for the Multi Charts page."""
    current = load_app_config()
    state = _normalize_multi_charts_settings(settings)
    current['multi_charts'] = state
    save_app_config(current)
    return state


def load_youtube_settings() -> Any:
    """Load persisted state for the YouTube page."""
    config = load_app_config()
    return _normalize_youtube_settings(config.get('youtube', {}))


def save_youtube_settings(settings: Any) -> Any:
    """Persist state for the YouTube page."""
    current = load_app_config()
    state = _normalize_youtube_settings(settings)
    current['youtube'] = state
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


def load_time_format() -> bool:
    """Load persisted 12h/24h time format preference."""
    config = load_app_config()
    return bool(config.get('time_12h', True))


def save_time_format(use_12h: bool) -> None:
    """Persist 12h/24h time format preference."""
    save_app_config({'time_12h': bool(use_12h)})
