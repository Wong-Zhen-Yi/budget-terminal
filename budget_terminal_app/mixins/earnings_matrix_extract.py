from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.workers.polygon import _get_fiscal_year

class EarningsMatrixExtractMixin:

    def _em_find_row(self, df: Any, search_keys: Any) -> Any:
        """Find a matching row in a DataFrame. Prioritizes exact matches, then substring matches."""
        if df is None or df.empty:
            return (None, None)
        idx_lower = {str(k).lower().strip(): k for k in df.index}
        for key in search_keys:
            key_clean = key.lower().strip()
            if key_clean in idx_lower:
                orig = idx_lower[key_clean]
                row_data = df.loc[orig]
                if isinstance(row_data, pd.DataFrame):
                    row_data = row_data.iloc[0]
                return (orig, row_data)
        for key in search_keys:
            key_clean = key.lower().strip()
            for low, orig in idx_lower.items():
                if key_clean in low:
                    row_data = df.loc[orig]
                    if isinstance(row_data, pd.DataFrame):
                        row_data = row_data.iloc[0]
                    return (orig, row_data)
        return (None, None)

    def _em_extract_metric_data(self) -> Any:
        """Extract quarterly + annual data for all metrics in EM_METRICS."""
        data = self.p2_current_data
        if not data:
            return {}
        info = data.get('info', {})
        fy_end_month = info.get('fiscalYearEndMonth', 12) or 12
        results = {}
        all_years_with_data = set()
        all_q_labels = set()
        for name, q_key, a_key, search_key, is_eps in EM_METRICS:
            q_df = data.get(q_key)
            a_df = data.get(a_key)
            search_keys = EM_METRICS_SEARCH.get(search_key, [search_key])
            quarterly = {}
            _, q_series = self._em_find_row(q_df, search_keys)
            if q_series is not None:
                for col in q_df.columns:
                    yr = _get_fiscal_year(col, fy_end_month)
                    if yr is None:
                        continue
                    try:
                        v = float(q_series[col])
                        if pd.isna(v):
                            v = None
                    except:
                        v = None
                    q_num = 0
                    if hasattr(col, 'month'):
                        q_num = (col.month - 1) // 3 + 1
                    else:
                        try:
                            ts = pd.to_datetime(str(col))
                            q_num = (ts.month - 1) // 3 + 1
                        except:
                            s_col = str(col).upper()
                            if 'Q1' in s_col:
                                q_num = 1
                            elif 'Q2' in s_col:
                                q_num = 2
                            elif 'Q3' in s_col:
                                q_num = 3
                            elif 'Q4' in s_col:
                                q_num = 4
                    if q_num > 0:
                        q_label = f'Q{q_num}'
                        if yr not in quarterly:
                            quarterly[yr] = {}
                        quarterly[yr][q_label] = v
                        if v is not None:
                            all_years_with_data.add(yr)
                            all_q_labels.add(q_label)
            annual = {}
            _, a_series = self._em_find_row(a_df, search_keys)
            if a_series is not None:
                for col in a_df.columns:
                    yr = _get_fiscal_year(col, fy_end_month)
                    if yr is None:
                        continue
                    try:
                        v = float(a_series[col])
                        if pd.isna(v):
                            v = None
                    except:
                        v = None
                    annual[yr] = v
                    if v is not None:
                        all_years_with_data.add(yr)
            metric_q_labels = set()
            for yr_data in quarterly.values():
                for ql, val in yr_data.items():
                    if val is not None:
                        metric_q_labels.add(ql)
            results[name] = {'quarterly': quarterly, 'annual': annual, 'q_labels': sorted(metric_q_labels) if metric_q_labels else [], 'is_eps': is_eps}
        if not all_years_with_data:
            curr_yr = datetime.datetime.now().year
            all_years_with_data = {curr_yr - i for i in range(3)}
        global_q_labels = sorted(all_q_labels) if all_q_labels else []
        sorted_years = sorted(list(all_years_with_data))
        return {'metrics': results, 'years': sorted_years, 'q_labels': global_q_labels}

    def _em_fmt_val(self, val: Any, is_eps: Any=False) -> Any:
        """Format a value for the earnings matrix table."""
        if val is None:
            return '—'
        if is_eps:
            return f'{val:.2f}'
        return fmt_num(val)

    def _render_earnings_matrix(self) -> None:
        """Render earnings matrix."""
        if not self.p2_current_data:
            return
        info = self.p2_current_data.get('info', {})
        currency = info.get('currency', 'USD')
        self.em_currency_lbl.setText(f'All values are in {currency} ({currency})')
        self._em_processed_data = self._em_extract_metric_data()
        if not self._em_processed_data or not self._em_processed_data['years']:
            return
        self._em_val_offset = 0
        self._em_gr_offset = 0
        self._em_sync_render()
