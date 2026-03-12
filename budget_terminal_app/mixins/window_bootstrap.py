from __future__ import annotations
from typing import Any
from ..compat import *

class WindowBootstrapMixin:

    def _portfolio_index_from_id(self, portfolio_id: Any) -> int:
        """Return the fixed slot index for a portfolio id."""
        portfolio_ids = list(PORTFOLIO_IDS)
        try:
            return portfolio_ids.index(str(portfolio_id or '').strip())
        except ValueError:
            return 0

    def _portfolio_id_from_index(self, index: Any) -> Any:
        """Return the fixed slot id for a tab index."""
        try:
            numeric = int(index)
        except (TypeError, ValueError):
            numeric = 0
        numeric = min(max(numeric, 0), len(PORTFOLIO_IDS) - 1)
        return PORTFOLIO_IDS[numeric]

    def _rebuild_portfolio_slots(self) -> None:
        """Mirror the persisted portfolio catalog into the UI-friendly slot list."""
        slots = []
        portfolios = self.all_portfolios_state.get('portfolios', {})
        for portfolio_id in PORTFOLIO_IDS:
            entry = portfolios.get(portfolio_id, {})
            slots.append({
                'id': self._portfolio_index_from_id(portfolio_id),
                'portfolio_id': portfolio_id,
                'name': str(entry.get('name', DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)) or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)),
            })
        self.portfolio_slots = slots
        self.main_portfolio_index = self._portfolio_index_from_id(self.main_portfolio_id)
        self.active_portfolio_index = self._portfolio_index_from_id(self.active_portfolio_id)

    def _get_portfolio_entry(self, portfolio_id: Any=None) -> Any:
        """Return a mutable portfolio entry from the runtime state."""
        pid = self._portfolio_id_from_index(self.active_portfolio_index if portfolio_id is None else self._portfolio_index_from_id(portfolio_id))
        entry = self.all_portfolios_state.setdefault('portfolios', {}).setdefault(pid, {
            'name': DEFAULT_PORTFOLIO_NAMES.get(pid, pid),
            'portfolio': [],
            'chart_slots': list(DEFAULT_CHART_SLOTS),
            'portfolio_tracker': {},
            'options_tracker': [],
        })
        entry.setdefault('portfolio', [])
        entry.setdefault('chart_slots', list(DEFAULT_CHART_SLOTS))
        entry.setdefault('portfolio_tracker', {})
        entry.setdefault('options_tracker', [])
        return entry

    def _apply_main_portfolio_runtime(self) -> None:
        """Sync app-wide runtime fields from the selected main portfolio."""
        entry = self._get_portfolio_entry(self.main_portfolio_id)
        self.tickers = entry['portfolio']
        self.chart_slots = entry['chart_slots']
        self.tracker_data = entry['portfolio_tracker']

    def _apply_active_portfolio_editor_state(self) -> None:
        """Sync page-4 editor fields from the selected active portfolio."""
        entry = self._get_portfolio_entry(self.active_portfolio_id)
        self.active_tickers = entry['portfolio']
        self.active_tracker_data = entry['portfolio_tracker']
        self.options_data = entry['options_tracker']
        self.active_options_data = self.options_data

    def _save_active_options_data(self) -> None:
        """Persist page-4 options rows to the selected active portfolio."""
        self._get_portfolio_entry(self.active_portfolio_id)['options_tracker'] = list(self.options_data)
        self._persist_all_portfolios()

    def _active_portfolio_uses_main_runtime(self) -> bool:
        """Return whether the portfolio editor is currently showing the app-wide main portfolio."""
        return self.active_portfolio_id == self.main_portfolio_id

    def _get_fetch_tickers(self) -> Any:
        """Return the deduplicated ticker set needed across saved portfolios."""
        combined = []
        for portfolio_id in PORTFOLIO_IDS:
            entry = self._get_portfolio_entry(portfolio_id)
            for ticker in list(entry.get('portfolio', [])):
                text = str(ticker or '').upper().strip()
                if text and text not in combined:
                    combined.append(text)
        return combined

    def _persist_all_portfolios(self) -> None:
        """Persist the full runtime portfolio state."""
        self.all_portfolios_state['main_portfolio_id'] = self.main_portfolio_id
        self.all_portfolios_state['active_portfolio_id'] = self.active_portfolio_id
        save_all_portfolios_state(self.all_portfolios_state)

    def _sync_after_portfolio_change(self, *, refresh_main: bool=False) -> None:
        """Refresh derived runtime fields and visible page-4 widgets."""
        self._rebuild_portfolio_slots()
        self._apply_main_portfolio_runtime()
        self._apply_active_portfolio_editor_state()
        if hasattr(self, '_sync_chart_slot_inputs'):
            self._sync_chart_slot_inputs()
        if hasattr(self, '_reload_options_table'):
            self._reload_options_table()
        if hasattr(self, '_p4_refresh_portfolio_selector'):
            self._p4_refresh_portfolio_selector()
        if hasattr(self, '_p10_rebuild_watchlists'):
            self._p10_rebuild_watchlists()
        if hasattr(self, '_p6_update_total'):
            self._p6_update_total()
        if hasattr(self, '_p7_refresh_options_expirations'):
            self._p7_refresh_options_expirations()
        if getattr(self, 'last_data', None):
            self.update_page4(self.last_data)
            self.repopulate_portfolio()
        if refresh_main:
            self.last_data = None
            self.refresh_data()

    def set_active_portfolio_index(self, index: Any) -> None:
        """Switch the page-4 editor to a different portfolio slot."""
        self.active_portfolio_id = self._portfolio_id_from_index(index)
        self.all_portfolios_state['active_portfolio_id'] = self.active_portfolio_id
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=False)

    def rename_portfolio(self, index: Any, name: Any) -> None:
        """Rename one of the fixed portfolio slots."""
        portfolio_id = self._portfolio_id_from_index(index)
        clean_name = str(name or '').strip() or DEFAULT_PORTFOLIO_NAMES.get(portfolio_id, portfolio_id)
        self._get_portfolio_entry(portfolio_id)['name'] = clean_name
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=False)

    def set_main_portfolio_index(self, index: Any) -> None:
        """Promote the selected portfolio slot to the app-wide main portfolio."""
        self.main_portfolio_id = self._portfolio_id_from_index(index)
        self.all_portfolios_state['main_portfolio_id'] = self.main_portfolio_id
        self._persist_all_portfolios()
        self._sync_after_portfolio_change(refresh_main=True)

    def __init__(self) -> None:
        """Initialize the object."""
        super().__init__()
        self._invoke_main.connect(self._on_invoke_main)
        self.setWindowTitle('Budget Terminal')
        self.resize(1280, 800)
        self.all_portfolios_state = load_all_portfolios_state()
        self.main_portfolio_id = self.all_portfolios_state.get('main_portfolio_id', PORTFOLIO_IDS[0])
        self.active_portfolio_id = self.all_portfolios_state.get('active_portfolio_id', self.main_portfolio_id)
        self._rebuild_portfolio_slots()
        self.tickers = []
        self.chart_slots = []
        self.chart_timeframes = [('5y', '1wk'), ('5y', '1wk'), ('5y', '1wk')]
        self.last_data = None
        self.p2_current_data = None
        self.tracker_data = {}
        self._mktcap_cache = {}
        self._return_metrics_cache = {}
        self._return_metrics_fetching = {}
        self._active_return_timeframe = 'dip_finder'
        self._news_auto_summarized = False
        self._data_collection_ts = None
        self._data_collection_sources = []
        self.options_data = []
        self.active_tickers = []
        self.active_tracker_data = {}
        self.active_options_data = []
        self.networth_data = load_networth_data()
        self.theme_settings = load_theme_settings()
        self.chart_page_state = load_chart_page_settings()
        self.init_theme_system(apply=False)
        self.dashboard_chart_rows = [[], [], []]
        self.dashboard_chart_ma200 = [None, None, None]
        self.dashboard_chart_view_guards = [False, False, False]
        self._apply_main_portfolio_runtime()
        self._apply_active_portfolio_editor_state()
        self.init_ui()
        self.theme_manager.apply_theme(self.current_theme_id, persist=False)
        self._sync_after_portfolio_change(refresh_main=False)
        self.refresh_data()
        if self.p2_ticker_input.text().strip():
            QTimer.singleShot(200, self.analyze_stock_p2)

    def _on_invoke_main(self, fn: Any) -> None:
        """Handle invoke main."""
        fn()

    def _start_clock_timer(self) -> None:
        """Handle start clock timer."""
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
