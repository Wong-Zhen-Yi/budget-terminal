from __future__ import annotations
from typing import Any
from ..compat import *

class PolygonRenderMixin:

    def _p9_em_extract_data(self) -> Any:
        """Handle p9 em extract data."""
        data = self.p9_current_data
        if not data:
            return {}
        q_reports = data.get('polygon_quarterly', [])
        a_reports = data.get('polygon_annual', [])
        mapping = {'Sales': ('income_statement', ['revenues', 'operating_revenue', 'gross_profit']), 'EBITDA': ('income_statement', ['ebitda']), 'Net Income': ('income_statement', ['net_income_loss', 'net_income_loss_available_to_common_stockholders_basic']), 'EPS (GAAP)': ('income_statement', ['basic_earnings_per_share', 'diluted_earnings_per_share']), 'Total Assets': ('balance_sheet', ['assets', 'total_assets']), 'Current Assets': ('balance_sheet', ['current_assets']), 'Current Liabilities': ('balance_sheet', ['current_liabilities']), 'Shareholder Equity': ('balance_sheet', ['equity', 'stockholders_equity']), 'Cash Flow From Operations': ('cash_flow_statement', ['net_cash_flow_from_operating_activities', 'net_cash_provided_by_operating_activities']), 'Cash Flow From Investing': ('cash_flow_statement', ['net_cash_flow_from_investing_activities', 'net_cash_provided_by_investing_activities']), 'Cash Flow From Financing': ('cash_flow_statement', ['net_cash_flow_from_financing_activities', 'net_cash_provided_by_financing_activities'])}
        results = {}
        all_years = set()
        logger.info(f"P9: Extracting data for {data['ticker']}...")
        for name, (category, keys) in mapping.items():
            is_eps = False
            for m_name, _, _, _, m_eps in P9_EM_METRICS:
                if m_name == name:
                    is_eps = m_eps
                    break
            quarterly = {}
            for report in q_reports:
                yr = int(report.get('fiscal_year', 0))
                fp = report.get('fiscal_period', '')
                if not yr or not fp:
                    continue
                if fp in ['Q1', 'Q2', 'Q3', 'Q4']:
                    norm_fp = fp
                elif fp == 'FY':
                    continue
                else:
                    continue
                all_years.add(yr)
                val = None
                cat_data = report.get('financials', {}).get(category, {})
                for k in keys:
                    if k in cat_data:
                        val = cat_data[k].get('value')
                        if val is not None:
                            break
                if yr not in quarterly:
                    quarterly[yr] = {}
                quarterly[yr][norm_fp] = val
            annual = {}
            combined_a = a_reports + [r for r in q_reports if r.get('fiscal_period') == 'FY']
            for report in combined_a:
                yr = int(report.get('fiscal_year', 0))
                if not yr:
                    continue
                all_years.add(yr)
                val = None
                cat_data = report.get('financials', {}).get(category, {})
                for k in keys:
                    if k in cat_data:
                        val = cat_data[k].get('value')
                        if val is not None:
                            break
                if yr not in annual or report in a_reports:
                    annual[yr] = val
            q_found = any((v is not None for y in quarterly.values() for v in y.values()))
            a_found = any((v is not None for v in annual.values()))
            if not q_found and (not a_found):
                logger.warning(f"P9: No data found for metric '{name}' (searched {keys} in {category})")
            results[name] = {'quarterly': quarterly, 'annual': annual, 'is_eps': is_eps}
        years_sorted = sorted(list(all_years))
        logger.info(f'P9: Extraction complete. Years found: {years_sorted}')
        return {'metrics': results, 'years': years_sorted}

    def _p9_sync_render(self) -> None:
        """Handle p9 sync render."""
        metric_name = self.p9_metric_combo.currentText()
        self._p9_render_tables(metric_name)
        self._p9_render_valuation()
        self._p9_render_charts(metric_name)

    def _p9_em_fmt_val(self, val: Any, is_eps: Any=False) -> Any:
        """Handle p9 em fmt val."""
        if val is None:
            return '—'
        return f'{val:.2f}' if is_eps else fmt_num(val)

    def _p9_render_tables(self, name: Any) -> Any:
        """Handle p9 render tables."""
        if not self.p9_em_processed or name not in self.p9_em_processed['metrics']:
            return
        d = self.p9_em_processed['metrics'][name]
        years = self.p9_em_processed['years']
        vis_years = years[-self.p9_em_visible_cols:]
        q_labels = ['Q1', 'Q2', 'Q3', 'Q4']
        is_eps = d['is_eps']
        mode = self.p9_em_mode
        vt = self.p9_table_values
        vt.setRowCount(6)
        vt.setColumnCount(1 + len(vis_years))
        vt.setHorizontalHeaderLabels([''] + [f'FY{y}' for y in vis_years])
        for r, ql in enumerate(q_labels):
            vt.setItem(r, 0, QTableWidgetItem(ql))
            for c, yr in enumerate(vis_years):
                val = d['quarterly'].get(yr, {}).get(ql)
                item = QTableWidgetItem(self._p9_em_fmt_val(val, is_eps))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if val is not None and val < 0:
                    item.setForeground(QColor('#ff5555'))
                vt.setItem(r, c + 1, item)
        vt.setItem(5, 0, QTableWidgetItem('Annual'))
        for c, yr in enumerate(vis_years):
            val = d['annual'].get(yr)
            item = QTableWidgetItem(self._p9_em_fmt_val(val, is_eps))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            if val is not None and val < 0:
                item.setForeground(QColor('#ff5555'))
            vt.setItem(5, c + 1, item)
        vt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        gt = self.p9_table_growth
        gt.setRowCount(6)
        gt.setColumnCount(1 + len(vis_years))
        gt.setHorizontalHeaderLabels([''] + [f'FY{y}' for y in vis_years])

        def _growth_item(cur: Any, prev: Any) -> Any:
            """Handle growth item."""
            if cur is None or prev is None or prev == 0:
                return QTableWidgetItem('—')
            g = (cur - prev) / abs(prev) * 100
            it = QTableWidgetItem(f'{g:+.1f}%')
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setForeground(QColor('#4caf50' if g >= 0 else '#ff5555'))
            return it
        for r, ql in enumerate(q_labels):
            gt.setItem(r, 0, QTableWidgetItem(ql))
            for c, yr in enumerate(vis_years):
                cur = d['quarterly'].get(yr, {}).get(ql)
                prev = None
                if mode == 'yoy':
                    prev = d['quarterly'].get(yr - 1, {}).get(ql)
                else:
                    q_idx = q_labels.index(ql)
                    if q_idx > 0:
                        prev = d['quarterly'].get(yr, {}).get(q_labels[q_idx - 1])
                    else:
                        prev = d['quarterly'].get(yr - 1, {}).get('Q4')
                gt.setItem(r, c + 1, _growth_item(cur, prev))
        gt.setItem(5, 0, QTableWidgetItem('Annual'))
        for c, yr in enumerate(vis_years):
            gt.setItem(5, c + 1, _growth_item(d['annual'].get(yr), d['annual'].get(yr - 1)))
        gt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def _p9_render_valuation(self) -> None:
        """Handle p9 render valuation."""
        for r in range(4):
            for c in range(1, 5):
                self.p9_valuation_table.setItem(r, c, QTableWidgetItem('N/A'))

    def _p9_render_charts(self, name: Any) -> None:
        """Handle p9 render charts."""
        if not self.p9_em_processed or name not in self.p9_em_processed['metrics']:
            return
        d = self.p9_em_processed['metrics'][name]
        years = self.p9_em_processed['years']
        self.p9_plot_values.clear()
        pw = self.p9_plot_values
        ann_vals = [d['annual'].get(y) for y in years if d['annual'].get(y) is not None]
        ann_years = [y for y in years if d['annual'].get(y) is not None]
        if ann_vals:
            pw.plot(ann_years, ann_vals, pen=pg.mkPen('#00e5cc', width=2), symbol='o', symbolBrush='#00e5cc')
            pw.getAxis('bottom').setTicks([[(y, str(y)) for y in years]])

    def _p9_em_set_growth_mode(self, mode: Any) -> None:
        """Handle p9 em set growth mode."""
        self.p9_em_mode = mode
        self.p9_yoy_btn.setChecked(mode == 'yoy')
        self.p9_pop_btn.setChecked(mode == 'pop')
        self._p9_sync_render()
