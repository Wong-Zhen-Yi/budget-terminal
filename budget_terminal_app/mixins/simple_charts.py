from __future__ import annotations
from typing import Any
from ..compat import *

class SimpleChartsMixin:

    def _render_simple_charts(self, data: Any, period: Any) -> Any:
        """Render simple charts."""
        fin_df = data['financials'] if period == 'annual' else data['quarterly_financials']
        bs_df = data['balance_sheet'] if period == 'annual' else data['quarterly_balance_sheet']
        cf_df = data['cashflow'] if period == 'annual' else data['quarterly_cashflow']
        info = data['info']

        def _col_label(c: Any) -> Any:
            """Handle col label."""
            if period == 'annual':
                return c.strftime('%Y') if hasattr(c, 'strftime') else str(c)[:4]
            else:
                return f"{c.strftime('%Y')}-Q{(c.month - 1) // 3 + 1}" if hasattr(c, 'strftime') else str(c)[:7]

        def _ordered_cols(df: Any) -> Any:
            """Return dataframe columns in chronological order."""
            cols = list(df.columns)
            try:
                return sorted(cols)
            except Exception:
                return list(reversed(cols))

        def _get_series(df: Any, keys: Any) -> Any:
            """Returns (vals, labels, cols) — NaN entries are skipped entirely."""
            if df is None or df.empty:
                return ([], [], [])
            idx_lower = {str(k).lower(): k for k in df.index}
            for key in keys:
                for low, orig in idx_lower.items():
                    if key in low:
                        all_cols = _ordered_cols(df)
                        vals, labels, valid_cols = ([], [], [])
                        for c in all_cols:
                            try:
                                v = float(df.at[orig, c])
                                if not pd.isna(v):
                                    vals.append(v)
                                    labels.append(_col_label(c))
                                    valid_cols.append(c)
                            except Exception:
                                pass
                        if vals:
                            return (vals, labels, valid_cols)
            return ([], [], [])

        def _solid_bars(x: Any, heights: Any, color: Any, width: Any=0.7) -> Any:
            """Handle solid bars."""
            brush = pg.mkBrush(color)
            pen = pg.mkPen(color, width=1)
            return pg.BarGraphItem(x=x, height=heights, width=width, brush=brush, pen=pen)

        def _add_labels(pw: Any, x_positions: Any, heights: Any, color: Any=None, grouped: Any=False) -> None:
            """Handle add labels."""
            color = color or self.theme_color('text_primary')
            font = pg.QtGui.QFont('Arial', 8 if grouped else 10, pg.QtGui.QFont.Weight.Bold)
            for i, (xi, h) in enumerate(zip(x_positions, heights)):
                if h == 0:
                    continue
                above = h >= 0
                anchor = (0.5, 1.0 if above else 0.0)
                if grouped:
                    txt = fmt_num(h)
                else:
                    txt = fmt_num(h)
                    if i > 0 and heights[i - 1] != 0:
                        prev = heights[i - 1]
                        pct = (h - prev) / abs(prev) * 100
                        pct_str = f'(+{pct:.1f}%)' if pct >= 0 else f'({pct:.1f}%)'
                        txt = f'{fmt_num(h)} {pct_str}'
                item = pg.TextItem(txt, color=color, anchor=anchor)
                item.setFont(font)
                item.setPos(xi, h)
                pw.addItem(item)

        def _set_y_range(pw: Any, all_vals: Any) -> None:
            """Handle set y range."""
            nonzero = [v for v in all_vals if v != 0]
            if not nonzero:
                return
            y_max = max(nonzero) if max(nonzero) > 0 else 0
            y_min = min(nonzero) if min(nonzero) < 0 else 0
            data_range = abs(y_max - y_min) or abs(y_max or y_min)
            pad_top = max(abs(y_max) * 0.22, data_range * 0.15) if y_max >= 0 else 0
            pad_bot = max(abs(y_min) * 0.22, data_range * 0.15) if y_min <= 0 else 0
            pw.setYRange(y_min - pad_bot, y_max + pad_top, padding=0)

        def _set_ticks(pw: Any, labels: Any) -> None:
            """Handle set ticks."""
            pw.getAxis('bottom').setTicks([[(i, lbl) for i, lbl in enumerate(labels)]])
            pw.getAxis('bottom').setStyle(tickFont=pg.QtGui.QFont('Arial', 7))

        def _set_x_range(pw: Any, n: Any) -> None:
            """Handle set x range."""
            pw.setXRange(-0.6, n - 0.4, padding=0)

        def _grouped_chart(pw: Any, legend_bar: Any, series_list: Any, offsets: Any, legend_items: Any) -> None:
            """Plot grouped bars with a shared timeline from the union of all series dates."""
            all_cols = sorted(set((c for _, _, cols in series_list for c in cols)))
            if not all_cols:
                return
            col_idx = {c: i for i, c in enumerate(all_cols)}
            labels = [_col_label(c) for c in all_cols]
            n = len(all_cols)
            bar_layout = legend_bar.layout()
            for i in reversed(range(bar_layout.count())):
                w = bar_layout.itemAt(i).widget()
                if w:
                    w.deleteLater()
            for color, _, name in legend_items:
                swatch = QLabel()
                swatch.setFixedSize(12, 12)
                swatch.setStyleSheet(f'background: {color}; border-radius: 2px;')
                text = QLabel(name)
                text.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 11px; background: transparent;')
                bar_layout.addWidget(swatch)
                bar_layout.addWidget(text)
                bar_layout.addSpacing(12)
            all_vals = []
            for (vals, _, cols), offset, (color, label_color, name) in zip(series_list, offsets, legend_items):
                if not vals:
                    continue
                x = [col_idx[c] + offset for c in cols]
                item = _solid_bars(x, vals, color, width=0.42)
                pw.addItem(item)
                _add_labels(pw, x, vals, label_color, grouped=True)
                all_vals.extend(vals)
            _set_ticks(pw, labels)
            _set_x_range(pw, n)
            _set_y_range(pw, all_vals)

        def _clear_legend_bar(legend_bar: Any) -> None:
            """Handle clear legend bar."""
            bar_layout = legend_bar.layout()
            for i in reversed(range(bar_layout.count())):
                w = bar_layout.itemAt(i).widget()
                if w:
                    w.deleteLater()
        pw = self.p2_simple_charts[0]
        pw.clear()
        _clear_legend_bar(self.p2_simple_legend_bars[0])
        vals, labels, _ = _get_series(fin_df, ['total revenue'])
        if vals:
            x = list(range(len(vals)))
            pw.addItem(_solid_bars(x, vals, self.theme_series_color(0)))
            _add_labels(pw, x, vals, self.theme_color('text_secondary'))
            _set_ticks(pw, labels)
            _set_x_range(pw, len(vals))
            _set_y_range(pw, vals)
        pw = self.p2_simple_charts[1]
        pw.clear()
        _clear_legend_bar(self.p2_simple_legend_bars[1])
        vals, labels, _ = _get_series(fin_df, ['net income'])
        if vals:
            x = list(range(len(vals)))
            pw.addItem(_solid_bars(x, vals, self.theme_series_color(1)))
            _add_labels(pw, x, vals, self.theme_color('text_secondary'))
            _set_ticks(pw, labels)
            _set_x_range(pw, len(vals))
            _set_y_range(pw, vals)
        pw = self.p2_simple_charts[2]
        pw.clear()
        _clear_legend_bar(self.p2_simple_legend_bars[2])
        op_series = _get_series(cf_df, ['operating cash flow', 'cash from operations'])
        fcf_series = _get_series(cf_df, ['free cash flow'])
        if op_series[0] or fcf_series[0]:
            _grouped_chart(pw, self.p2_simple_legend_bars[2], [op_series, fcf_series], [-0.22, +0.22], [(self.theme_series_color(2), self.theme_color('text_secondary'), 'Operating CF'), (self.theme_series_color(3), self.theme_color('text_secondary'), 'Free CF')])
        pw = self.p2_simple_charts[3]
        pw.clear()
        _clear_legend_bar(self.p2_simple_legend_bars[3])
        vals, labels, _ = _get_series(bs_df, ['ordinary shares number', 'shares outstanding', 'common stock shares outstanding'])
        if not vals:
            shares_scalar = info.get('sharesOutstanding')
            if shares_scalar is not None and fin_df is not None and (not fin_df.empty):
                all_fin_cols = _ordered_cols(fin_df)
                vals = [float(shares_scalar)] * len(all_fin_cols)
                labels = [_col_label(c) for c in all_fin_cols]
        if vals:
            x = list(range(len(vals)))
            pw.addItem(_solid_bars(x, vals, self.theme_series_color(4)))
            _add_labels(pw, x, vals, self.theme_color('text_secondary'))
            _set_ticks(pw, labels)
            _set_x_range(pw, len(vals))
            _set_y_range(pw, vals)
        pw = self.p2_simple_charts[4]
        pw.clear()
        _clear_legend_bar(self.p2_simple_legend_bars[4])
        cash_series = _get_series(bs_df, ['cash and cash equivalents', 'cash equivalents'])
        debt_series = _get_series(bs_df, ['total debt', 'long term debt'])
        if cash_series[0] or debt_series[0]:
            _grouped_chart(pw, self.p2_simple_legend_bars[4], [cash_series, debt_series], [-0.25, +0.25], [(self.theme_color('accent_positive'), self.theme_color('text_secondary'), 'Cash'), (self.theme_color('accent_negative'), self.theme_color('text_secondary'), 'Debt')])
        pw = self.p2_simple_charts[5]
        pw.clear()
        _clear_legend_bar(self.p2_simple_legend_bars[5])
        sga_series = _get_series(fin_df, ['selling general', 'general and administrative'])
        rd_series = _get_series(fin_df, ['research and development'])
        if sga_series[0] or rd_series[0]:
            _grouped_chart(pw, self.p2_simple_legend_bars[5], [sga_series, rd_series], [-0.25, +0.25], [(self.theme_series_color(0), self.theme_color('text_secondary'), 'SG&A'), (self.theme_series_color(1), self.theme_color('text_secondary'), 'R&D')])
