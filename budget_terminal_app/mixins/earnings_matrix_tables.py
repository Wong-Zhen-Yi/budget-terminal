from __future__ import annotations
from typing import Any
from ..compat import *

class EarningsMatrixTablesMixin:

    def _em_render_val_table(self, name: Any, vt: Any) -> None:
        """Render the absolute values table for a specific metric."""
        all_data = self._em_processed_data
        if not all_data or name not in all_data['metrics']:
            vt.setRowCount(0)
            return
        d = all_data['metrics'][name]
        years = all_data['years']
        n_years = len(years)
        vis = min(self._em_visible_cols, n_years)
        offset = self._em_val_offset
        visible_years = years[offset:offset + vis]
        q_labels = all_data.get('q_labels', d.get('q_labels', []))
        is_eps = d['is_eps']
        has_quarterly = len(q_labels) > 0
        n_rows = len(q_labels) + 2 if has_quarterly else 1
        n_cols = 1 + len(visible_years)
        vt.setRowCount(n_rows)
        vt.setColumnCount(n_cols)
        headers = [''] + [f'FY {y}' for y in visible_years]
        vt.setHorizontalHeaderLabels(headers)
        if has_quarterly:
            for row_i, ql in enumerate(q_labels):
                lbl_item = QTableWidgetItem(ql)
                lbl_item.setForeground(QColor('#aaa'))
                vt.setItem(row_i, 0, lbl_item)
                for col_i, yr in enumerate(visible_years):
                    val = d['quarterly'].get(yr, {}).get(ql)
                    text = self._em_fmt_val(val, is_eps)
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if val is not None and val < 0:
                        item.setForeground(QColor('#f44336'))
                    vt.setItem(row_i, col_i + 1, item)
            sep_row = len(q_labels)
            for c in range(n_cols):
                vt.setItem(sep_row, c, QTableWidgetItem(''))
            vt.setRowHeight(sep_row, 4)
        ann_row = len(q_labels) + 1 if has_quarterly else 0
        lbl_ann = QTableWidgetItem('Annual')
        lbl_ann.setForeground(QColor('#aaa'))
        font = lbl_ann.font()
        font.setBold(True)
        lbl_ann.setFont(font)
        vt.setItem(ann_row, 0, lbl_ann)
        for col_i, yr in enumerate(visible_years):
            val = d['annual'].get(yr)
            text = self._em_fmt_val(val, is_eps)
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            if val is not None and val < 0:
                item.setForeground(QColor('#f44336'))
            vt.setItem(ann_row, col_i + 1, item)
        vt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        vt.verticalHeader().setDefaultSectionSize(24)

    def _em_render_growth_table(self, name: Any, gt: Any) -> Any:
        """Render the growth % table for a specific metric."""
        all_data = self._em_processed_data
        if not all_data or name not in all_data['metrics']:
            gt.setRowCount(0)
            return
        d = all_data['metrics'][name]
        years = all_data['years']
        n_years = len(years)
        vis = min(self._em_visible_cols, n_years)
        offset = self._em_gr_offset
        visible_years = years[offset:offset + vis]
        q_labels = all_data.get('q_labels', d.get('q_labels', []))
        mode = self._em_growth_mode
        has_quarterly = len(q_labels) > 0
        n_rows = len(q_labels) + 2 if has_quarterly else 1
        n_cols = 1 + len(visible_years)
        gt.setRowCount(n_rows)
        gt.setColumnCount(n_cols)
        headers = [''] + [f'FY {y}' for y in visible_years]
        gt.setHorizontalHeaderLabels(headers)

        def _calc_growth(current: Any, previous: Any) -> Any:
            """Handle calc growth."""
            if current is None or previous is None or previous == 0:
                return None
            return (current - previous) / abs(previous) * 100

        def _growth_item(growth: Any) -> Any:
            """Handle growth item."""
            if growth is not None:
                item = QTableWidgetItem(f'{growth:+.1f}%')
                item.setForeground(QColor('#4caf50' if growth >= 0 else '#f44336'))
            else:
                item = QTableWidgetItem('—')
                item.setForeground(QColor('#555'))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return item
        if has_quarterly:
            for row_i, ql in enumerate(q_labels):
                lbl_item = QTableWidgetItem(ql)
                lbl_item.setForeground(QColor('#aaa'))
                gt.setItem(row_i, 0, lbl_item)
                for col_i, yr in enumerate(visible_years):
                    cur_val = d['quarterly'].get(yr, {}).get(ql)
                    if mode == 'yoy':
                        prev_val = d['quarterly'].get(yr - 1, {}).get(ql)
                    else:
                        q_idx = q_labels.index(ql)
                        if q_idx > 0:
                            prev_val = d['quarterly'].get(yr, {}).get(q_labels[q_idx - 1])
                        else:
                            prev_val = d['quarterly'].get(yr - 1, {}).get(q_labels[-1])
                    gt.setItem(row_i, col_i + 1, _growth_item(_calc_growth(cur_val, prev_val)))
            sep_row = len(q_labels)
            for c in range(n_cols):
                gt.setItem(sep_row, c, QTableWidgetItem(''))
            gt.setRowHeight(sep_row, 4)
        ann_row = len(q_labels) + 1 if has_quarterly else 0
        lbl_ann = QTableWidgetItem('Annual')
        lbl_ann.setForeground(QColor('#aaa'))
        font = lbl_ann.font()
        font.setBold(True)
        lbl_ann.setFont(font)
        gt.setItem(ann_row, 0, lbl_ann)
        for col_i, yr in enumerate(visible_years):
            cur_val = d['annual'].get(yr)
            prev_val = d['annual'].get(yr - 1)
            item = _growth_item(_calc_growth(cur_val, prev_val))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            gt.setItem(ann_row, col_i + 1, item)
        gt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        gt.verticalHeader().setDefaultSectionSize(24)

    def _em_render_ratios_table(self) -> Any:
        """Render the valuation ratios table (P/E, P/S, P/B, P/CF)."""
        data = self.p2_current_data
        if not data:
            return
        info = data.get('info', {})

        def sg(k: Any) -> Any:
            """Handle sg."""
            v = info.get(k)
            if v is None:
                return None
            try:
                v = float(v)
                return v if not pd.isna(v) else None
            except (TypeError, ValueError):
                return None
        trailing_pe = sg('trailingPE')
        if trailing_pe is None:
            price = sg('currentPrice')
            eps = sg('trailingEps')
            if price and eps and (eps != 0):
                trailing_pe = price / eps
        forward_pe = sg('forwardPE')
        ps = sg('priceToSalesTrailing12Months')
        pb = sg('priceToBook')
        mcap = sg('marketCap')
        ocf = sg('operatingCashflow')
        pcf = mcap / ocf if mcap and ocf and (ocf != 0) else None
        now = datetime.datetime.now()
        fy0 = now.year
        fy1 = fy0 + 1
        rows_data = [('P/E', trailing_pe, forward_pe), ('P/S', ps, None), ('P/B', pb, None), ('P/CF', pcf, None)]
        self.em_ratios_table.setRowCount(len(rows_data))
        self.em_ratios_table.setColumnCount(5)
        self.em_ratios_table.setHorizontalHeaderLabels(['Ratio', f'Last 4Q', f'Next 4Q', f'FY {fy0}', f'FY {fy1}'])
        for row_i, (label, trailing, forward) in enumerate(rows_data):
            lbl_item = QTableWidgetItem(label)
            lbl_item.setForeground(QColor('#aaa'))
            lbl_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.em_ratios_table.setItem(row_i, 0, lbl_item)
            for col_i, val in enumerate([trailing, forward, trailing, forward]):
                if val is not None:
                    text = f'{val:.1f}x'
                    color = '#4caf50'
                else:
                    text = '—'
                    color = '#555'
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setForeground(QColor(color))
                self.em_ratios_table.setItem(row_i, col_i + 1, item)
        self.em_ratios_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.em_ratios_table.verticalHeader().setDefaultSectionSize(26)

    def _em_sync_render(self) -> None:
        """Render all table pairs using current offsets."""
        for name, (vt, gt, v_hdr, g_hdr) in self.em_table_pairs.items():
            self._em_render_val_table(name, vt)
            self._em_render_growth_table(name, gt)
        self._em_render_ratios_table()

    def _em_set_growth_mode(self, mode: Any) -> None:
        """Handle em set growth mode."""
        self._em_growth_mode = mode
        self.em_growth_yoy_btn.setChecked(mode == 'yoy')
        self.em_growth_pop_btn.setChecked(mode == 'pop')
        self._em_sync_render()
