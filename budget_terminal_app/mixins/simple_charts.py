from __future__ import annotations
from typing import Any
from ..compat import *


class SimpleChartsMixin:

    def _p2_curated_metric_groups(self) -> list[tuple[str, list[str]]]:
        """Return the grouped metric catalog shown in the custom Fundamentals editor."""
        return [
            ('Income Statement', ['revenue', 'gross_profit', 'operating_income', 'ebitda', 'net_income']),
            ('Cash Flow', ['operating_cash_flow', 'free_cash_flow', 'capital_expenditure']),
            ('Balance Sheet', ['cash', 'total_debt', 'shares_outstanding', 'total_assets', 'shareholder_equity', 'current_assets', 'current_liabilities']),
            ('Derived', ['net_cash', 'current_ratio']),
        ]

    def _p2_curated_metric_specs(self) -> dict[str, dict[str, Any]]:
        """Return curated Fundamentals metric metadata and extraction rules."""
        return {
            'revenue': {
                'label': 'Revenue',
                'kind': 'statement',
                'family': 'financials',
                'keys': ['total revenue', 'revenue', 'operating revenue'],
                'color': self.theme_series_color(0),
            },
            'gross_profit': {
                'label': 'Gross Profit',
                'kind': 'statement',
                'family': 'financials',
                'keys': ['gross profit'],
                'color': self.theme_series_color(1),
            },
            'operating_income': {
                'label': 'Operating Income',
                'kind': 'statement',
                'family': 'financials',
                'keys': ['operating income', 'income from operations'],
                'color': self.theme_series_color(2),
            },
            'ebitda': {
                'label': 'EBITDA',
                'kind': 'statement',
                'family': 'financials',
                'keys': ['ebitda'],
                'color': self.theme_series_color(3),
            },
            'net_income': {
                'label': 'Net Income',
                'kind': 'statement',
                'family': 'financials',
                'keys': ['net income'],
                'color': self.theme_series_color(4),
            },
            'operating_cash_flow': {
                'label': 'Operating Cash Flow',
                'kind': 'statement',
                'family': 'cashflow',
                'keys': ['operating cash flow', 'cash from operations', 'net cash provided by operating activities'],
                'color': self.theme_series_color(2),
            },
            'free_cash_flow': {
                'label': 'Free Cash Flow',
                'kind': 'statement',
                'family': 'cashflow',
                'keys': ['free cash flow'],
                'color': self.theme_series_color(3),
            },
            'capital_expenditure': {
                'label': 'Capital Expenditure',
                'kind': 'statement',
                'family': 'cashflow',
                'keys': ['capital expenditure', 'capital expenditures', 'purchase of ppe'],
                'color': self.theme_color('accent_negative'),
            },
            'cash': {
                'label': 'Cash',
                'kind': 'sum',
                'family': 'balance_sheet',
                'groups': [
                    ['cash cash equivalents and short term investments', 'cash and cash equivalents', 'cash equivalents'],
                    ['available for sale securities', 'marketable securities'],
                ],
                'color': self.theme_color('accent_positive'),
            },
            'total_debt': {
                'label': 'Total Debt',
                'kind': 'debt',
                'family': 'balance_sheet',
                'color': self.theme_color('accent_negative'),
            },
            'shares_outstanding': {
                'label': 'Shares Outstanding',
                'kind': 'shares',
                'family': 'balance_sheet',
                'keys': ['ordinary shares number', 'shares outstanding', 'common stock shares outstanding'],
                'color': self.theme_series_color(4),
            },
            'total_assets': {
                'label': 'Total Assets',
                'kind': 'statement',
                'family': 'balance_sheet',
                'keys': ['total assets'],
                'color': self.theme_series_color(0),
            },
            'shareholder_equity': {
                'label': 'Shareholder Equity',
                'kind': 'statement',
                'family': 'balance_sheet',
                'keys': ['stockholders equity', 'total stockholder equity', 'shareholders equity', 'common stock equity', 'total equity gross minority interest'],
                'color': self.theme_series_color(1),
            },
            'current_assets': {
                'label': 'Current Assets',
                'kind': 'statement',
                'family': 'balance_sheet',
                'keys': ['current assets', 'total current assets'],
                'color': self.theme_series_color(2),
            },
            'current_liabilities': {
                'label': 'Current Liabilities',
                'kind': 'statement',
                'family': 'balance_sheet',
                'keys': ['current liabilities', 'total current liabilities'],
                'color': self.theme_series_color(3),
            },
            'net_cash': {
                'label': 'Net Cash',
                'kind': 'difference',
                'left': 'cash',
                'right': 'total_debt',
                'color': self.theme_series_color(0),
            },
            'current_ratio': {
                'label': 'Current Ratio',
                'kind': 'ratio',
                'numerator': 'current_assets',
                'denominator': 'current_liabilities',
                'color': self.theme_series_color(1),
            },
        }

    def _p2_curated_metric_label(self, key: Any) -> str:
        """Return the display label for one curated metric key."""
        metric = self._p2_curated_metric_specs().get(str(key or '').strip().lower(), {})
        return str(metric.get('label', str(key or '').replace('_', ' ').title()) or str(key or '').replace('_', ' ').title())

    def _p2_col_label(self, column: Any, period: Any) -> str:
        """Format one statement column label for the selected period."""
        if period == 'annual':
            return column.strftime('%Y') if hasattr(column, 'strftime') else str(column)[:4]
        if hasattr(column, 'strftime'):
            return f"{column.strftime('%Y')}-Q{(column.month - 1) // 3 + 1}"
        return str(column)[:7]

    def _p2_statement_frame(self, data: Any, family: Any, period: Any) -> Any:
        """Return the requested statement frame for the selected period."""
        if not isinstance(data, dict):
            return None
        family_key = str(family or 'financials').strip().lower()
        if family_key == 'cashflow':
            frame_key = 'cashflow' if period == 'annual' else 'quarterly_cashflow'
        elif family_key == 'balance_sheet':
            frame_key = 'balance_sheet' if period == 'annual' else 'quarterly_balance_sheet'
        else:
            frame_key = 'financials' if period == 'annual' else 'quarterly_financials'
        return data.get(frame_key)

    def _p2_ordered_statement_cols(self, df: Any) -> list[Any]:
        """Return DataFrame columns in chronological order when possible."""
        cols = list(getattr(df, 'columns', []))
        try:
            return sorted(cols)
        except Exception:
            return list(reversed(cols))

    def _p2_extract_statement_series(self, df: Any, keys: Any, period: Any) -> Any:
        """Return (values, labels, cols) for the first matching statement row."""
        if df is None or df.empty:
            return ([], [], [])
        idx_lower = {str(k).lower(): k for k in df.index}

        def _extract(orig: Any) -> Any:
            vals, labels, valid_cols = ([], [], [])
            for column in self._p2_ordered_statement_cols(df):
                try:
                    value = float(df.at[orig, column])
                    if not pd.isna(value):
                        vals.append(value)
                        labels.append(self._p2_col_label(column, period))
                        valid_cols.append(column)
                except Exception:
                    pass
            return (vals, labels, valid_cols) if vals else None

        for key in keys:
            key_text = str(key or '').strip().lower()
            if key_text in idx_lower:
                result = _extract(idx_lower[key_text])
                if result:
                    return result
        for key in keys:
            key_text = str(key or '').strip().lower()
            for low, orig in idx_lower.items():
                if key_text and key_text in low:
                    result = _extract(orig)
                    if result:
                        return result
        return ([], [], [])

    def _p2_sum_statement_series(self, df: Any, period: Any, *key_groups: Any) -> Any:
        """Sum multiple statement rows, aligned by reporting column."""
        combined = {}
        col_labels = {}
        for keys in key_groups:
            vals, labels, cols = self._p2_extract_statement_series(df, keys, period)
            for value, label, column in zip(vals, labels, cols):
                combined[column] = combined.get(column, 0.0) + value
                col_labels[column] = label
        if not combined:
            return ([], [], [])
        sorted_cols = sorted(combined.keys())
        return (
            [combined[column] for column in sorted_cols],
            [col_labels[column] for column in sorted_cols],
            sorted_cols,
        )

    def _p2_total_debt_series(self, df: Any, period: Any) -> Any:
        """Resolve total debt with fallbacks for statements that split debt rows."""
        total_debt = self._p2_extract_statement_series(df, ['total debt'], period)
        if total_debt[0]:
            return total_debt
        lease_total = self._p2_sum_statement_series(
            df,
            period,
            ['long term debt and capital lease obligation'],
            ['current debt and capital lease obligation'],
        )
        if lease_total[0]:
            return lease_total
        combined_debt = self._p2_sum_statement_series(
            df,
            period,
            ['long term debt'],
            ['current debt'],
        )
        if combined_debt[0]:
            return combined_debt
        return self._p2_extract_statement_series(df, ['long term debt'], period)

    def _p2_latest_total_debt_value(self, data: Any, period: Any='annual') -> Any:
        """Return the most recent total debt value from the selected statement period."""
        if not isinstance(data, dict):
            return None
        frame_key = 'balance_sheet' if period == 'annual' else 'quarterly_balance_sheet'
        values, _, _ = self._p2_total_debt_series(data.get(frame_key), period)
        return values[-1] if values else None

    def _p2_statement_rows_for_family(self, data: Any, family: Any) -> list[str]:
        """Return the union of visible statement rows for one family, preserving source order."""
        rows = {}
        ordered = []
        for period in ('annual', 'quarterly'):
            frame = self._p2_statement_frame(data, family, period)
            for row in list(getattr(frame, 'index', [])):
                row_text = str(row or '').strip()
                if row_text:
                    row_key = row_text.casefold()
                    if row_key not in rows:
                        rows[row_key] = row_text
                        ordered.append(row_text)
        return ordered

    def _p2_intersection_series_operation(self, left: Any, right: Any, op: Any) -> Any:
        """Combine two time series on their shared statement columns."""
        left_vals, left_labels, left_cols = left
        right_vals, _, right_cols = right
        left_map = {column: value for value, column in zip(left_vals, left_cols)}
        left_label_map = {column: label for label, column in zip(left_labels, left_cols)}
        right_map = {column: value for value, column in zip(right_vals, right_cols)}
        common_cols = [column for column in sorted(left_map.keys()) if column in right_map]
        if not common_cols:
            return ([], [], [])
        values = []
        labels = []
        for column in common_cols:
            try:
                value = op(float(left_map[column]), float(right_map[column]))
            except Exception:
                continue
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            values.append(value)
            labels.append(left_label_map.get(column, self._p2_col_label(column, 'annual')))
        return (values, labels, common_cols) if values else ([], [], [])

    def _p2_resolve_curated_series(self, data: Any, period: Any, metric_key: Any) -> tuple[list[Any], list[str], list[Any], str]:
        """Resolve one curated metric into chart-ready values and labels."""
        specs = self._p2_curated_metric_specs()
        key = str(metric_key or '').strip().lower()
        spec = specs.get(key)
        if spec is None:
            return ([], [], [], self.theme_series_color(0))
        family = spec.get('family', 'financials')
        color = str(spec.get('color', self.theme_series_color(0)) or self.theme_series_color(0))
        if spec.get('kind') == 'difference':
            left = self._p2_resolve_curated_series(data, period, spec.get('left'))
            right = self._p2_resolve_curated_series(data, period, spec.get('right'))
            values, labels, cols = self._p2_intersection_series_operation(
                (left[0], left[1], left[2]),
                (right[0], right[1], right[2]),
                lambda lhs, rhs: lhs - rhs,
            )
            return (values, labels, cols, color)
        if spec.get('kind') == 'ratio':
            left = self._p2_resolve_curated_series(data, period, spec.get('numerator'))
            right = self._p2_resolve_curated_series(data, period, spec.get('denominator'))
            values, labels, cols = self._p2_intersection_series_operation(
                (left[0], left[1], left[2]),
                (right[0], right[1], right[2]),
                lambda lhs, rhs: None if rhs in (None, 0) else lhs / rhs,
            )
            return (values, labels, cols, color)
        frame = self._p2_statement_frame(data, family, period)
        if spec.get('kind') == 'sum':
            values, labels, cols = self._p2_sum_statement_series(frame, period, *spec.get('groups', []))
            return (values, labels, cols, color)
        if spec.get('kind') == 'debt':
            values, labels, cols = self._p2_total_debt_series(frame, period)
            return (values, labels, cols, color)
        if spec.get('kind') == 'shares':
            values, labels, cols = self._p2_extract_statement_series(frame, spec.get('keys', []), period)
            if not values:
                shares_scalar = (data if isinstance(data, dict) else {}).get('info', {}).get('sharesOutstanding')
                if shares_scalar is not None:
                    try:
                        values = [float(shares_scalar)]
                        labels = ['Current']
                        cols = ['current']
                    except Exception:
                        values, labels, cols = ([], [], [])
            return (values, labels, cols, color)
        values, labels, cols = self._p2_extract_statement_series(frame, spec.get('keys', []), period)
        return (values, labels, cols, color)

    def _p2_clear_legend_bar(self, legend_bar: Any) -> None:
        """Remove all widgets from one inline legend row."""
        bar_layout = legend_bar.layout()
        if bar_layout is None:
            return
        for index in reversed(range(bar_layout.count())):
            widget = bar_layout.itemAt(index).widget()
            if widget:
                widget.deleteLater()

    def _p2_solid_bars(self, x_values: Any, heights: Any, color: Any, width: float=0.7) -> Any:
        """Build one solid bar series for a Fundamentals plot."""
        brush = pg.mkBrush(color)
        pen = pg.mkPen(color, width=1)
        return pg.BarGraphItem(x=x_values, height=heights, width=width, brush=brush, pen=pen)

    def _p2_add_bar_labels(self, pw: Any, x_positions: Any, heights: Any, color: Any=None, *, grouped: bool=False) -> None:
        """Annotate bars with formatted values and optional growth percentages."""
        color = color or self.theme_color('text_primary')
        font = pg.QtGui.QFont('Arial', 8 if grouped else 10, pg.QtGui.QFont.Weight.Bold)
        for index, (x_value, height) in enumerate(zip(x_positions, heights)):
            if height == 0:
                continue
            above = height >= 0
            anchor = (0.5, 1.0 if above else 0.0)
            text = fmt_num(height)
            if (not grouped) and index > 0 and heights[index - 1] != 0:
                previous = heights[index - 1]
                try:
                    pct = (height - previous) / abs(previous) * 100
                    pct_text = f'(+{pct:.1f}%)' if pct >= 0 else f'({pct:.1f}%)'
                    text = f'{fmt_num(height)} {pct_text}'
                except Exception:
                    text = fmt_num(height)
            item = pg.TextItem(text, color=color, anchor=anchor)
            item.setFont(font)
            item.setPos(x_value, height)
            pw.addItem(item)

    def _p2_set_plot_y_range(self, pw: Any, values: Any) -> None:
        """Apply a comfortable Y-range around a bar series."""
        nonzero = [value for value in values if value != 0]
        if not nonzero:
            return
        y_max = max(nonzero) if max(nonzero) > 0 else 0
        y_min = min(nonzero) if min(nonzero) < 0 else 0
        data_range = abs(y_max - y_min) or abs(y_max or y_min)
        pad_top = max(abs(y_max) * 0.22, data_range * 0.15) if y_max >= 0 else 0
        pad_bottom = max(abs(y_min) * 0.22, data_range * 0.15) if y_min <= 0 else 0
        pw.setYRange(y_min - pad_bottom, y_max + pad_top, padding=0)

    def _p2_set_plot_ticks(self, pw: Any, labels: Any) -> None:
        """Apply statement-period labels to the plot X-axis."""
        pw.getAxis('bottom').setTicks([[(index, label) for index, label in enumerate(labels)]])
        pw.getAxis('bottom').setStyle(tickFont=pg.QtGui.QFont('Arial', 7))

    def _p2_set_plot_x_range(self, pw: Any, count: int) -> None:
        """Apply a fixed X-range for one bar chart."""
        pw.setXRange(-0.6, count - 0.4, padding=0)

    def _p2_plot_single_series(self, pw: Any, legend_bar: Any, values: Any, labels: Any, color: Any) -> None:
        """Render one single-series Fundamentals chart."""
        pw.clear()
        self._p2_clear_legend_bar(legend_bar)
        if not values:
            return
        x_values = list(range(len(values)))
        pw.addItem(self._p2_solid_bars(x_values, values, color))
        self._p2_add_bar_labels(pw, x_values, values, self.theme_color('text_secondary'))
        self._p2_set_plot_ticks(pw, labels)
        self._p2_set_plot_x_range(pw, len(values))
        self._p2_set_plot_y_range(pw, values)

    def _p2_plot_grouped_series(self, pw: Any, legend_bar: Any, series_list: Any, offsets: Any, legend_items: Any) -> None:
        """Render one grouped Fundamentals chart on a shared statement timeline."""
        pw.clear()
        self._p2_clear_legend_bar(legend_bar)
        all_cols = sorted(set(column for _, _, cols in series_list for column in cols))
        if not all_cols:
            return
        col_index = {column: index for index, column in enumerate(all_cols)}
        labels = [self._p2_col_label(column, self._p2_period()) for column in all_cols]
        bar_layout = legend_bar.layout()
        if bar_layout is not None:
            for color, _, name in legend_items:
                swatch = QLabel()
                swatch.setFixedSize(12, 12)
                swatch.setStyleSheet(f'background: {color}; border-radius: 2px;')
                text = QLabel(name)
                text.setStyleSheet(f'color: {self.theme_color("text_primary")}; font-size: 11px; background: transparent;')
                bar_layout.addWidget(swatch)
                bar_layout.addWidget(text)
                bar_layout.addSpacing(12)
        all_values = []
        for (values, _, cols), offset, (color, label_color, _) in zip(series_list, offsets, legend_items):
            if not values:
                continue
            x_values = [col_index[column] + offset for column in cols]
            pw.addItem(self._p2_solid_bars(x_values, values, color, width=0.42))
            self._p2_add_bar_labels(pw, x_values, values, label_color, grouped=True)
            all_values.extend(values)
        self._p2_set_plot_ticks(pw, labels)
        self._p2_set_plot_x_range(pw, len(all_cols))
        self._p2_set_plot_y_range(pw, all_values)

    def _p2_render_custom_panel(self, widget_info: Any, descriptor: Any, data: Any, period: Any) -> None:
        """Render one custom Fundamentals panel from a checked raw statement row."""
        title_label = widget_info.get('title')
        status_label = widget_info.get('status')
        legend_bar = widget_info.get('legend')
        pw = widget_info.get('plot')
        title = str((descriptor or {}).get('title', '') or 'Custom').strip()
        title_label.setText(title)
        pw.clear()
        self._p2_clear_legend_bar(legend_bar)
        family = str((descriptor or {}).get('family', 'financials') or 'financials').strip().lower()
        row_name = str((descriptor or {}).get('row', '') or '').strip()
        frame = self._p2_statement_frame(data, family, period)
        values, labels, _ = self._p2_extract_statement_series(frame, [row_name], period)
        color = self.theme_series_color(0)
        if values:
            status_label.setVisible(False)
            x_values = list(range(len(values)))
            pw.addItem(self._p2_solid_bars(x_values, values, color))
            self._p2_add_bar_labels(pw, x_values, values, self.theme_color('text_secondary'))
            self._p2_set_plot_ticks(pw, labels)
            self._p2_set_plot_x_range(pw, len(values))
            self._p2_set_plot_y_range(pw, values)
            return
        status_label.setText('No data for this period.')
        status_label.setVisible(True)
        pw.getAxis('bottom').setTicks([[]])
        pw.getPlotItem().vb.autoRange()

    def _render_simple_charts(self, data: Any, period: Any) -> Any:
        """Render the fixed Default Fundamentals configuration."""
        fin_df = data['financials'] if period == 'annual' else data['quarterly_financials']
        bs_df = data['balance_sheet'] if period == 'annual' else data['quarterly_balance_sheet']
        cf_df = data['cashflow'] if period == 'annual' else data['quarterly_cashflow']
        info = data['info']

        values, labels, _, color = self._p2_resolve_curated_series(data, period, 'revenue')
        self._p2_plot_single_series(self.p2_simple_charts[0], self.p2_simple_legend_bars[0], values, labels, color)

        values, labels, _, color = self._p2_resolve_curated_series(data, period, 'net_income')
        self._p2_plot_single_series(self.p2_simple_charts[1], self.p2_simple_legend_bars[1], values, labels, color)

        operating_cf = self._p2_extract_statement_series(cf_df, ['operating cash flow', 'cash from operations'], period)
        free_cf = self._p2_extract_statement_series(cf_df, ['free cash flow'], period)
        self._p2_plot_grouped_series(
            self.p2_simple_charts[2],
            self.p2_simple_legend_bars[2],
            [operating_cf, free_cf],
            [-0.22, +0.22],
            [
                (self.theme_series_color(2), self.theme_color('text_secondary'), 'Operating CF'),
                (self.theme_series_color(3), self.theme_color('text_secondary'), 'Free CF'),
            ],
        )

        shares = self._p2_extract_statement_series(bs_df, ['ordinary shares number', 'shares outstanding', 'common stock shares outstanding'], period)
        if not shares[0]:
            shares_scalar = info.get('sharesOutstanding')
            if shares_scalar is not None:
                try:
                    shares = ([float(shares_scalar)], ['Current'], ['current'])
                except Exception:
                    shares = ([], [], [])
        self._p2_plot_single_series(
            self.p2_simple_charts[3],
            self.p2_simple_legend_bars[3],
            shares[0],
            shares[1],
            self.theme_series_color(4),
        )

        cash_series = self._p2_sum_statement_series(
            bs_df,
            period,
            ['cash cash equivalents and short term investments', 'cash and cash equivalents', 'cash equivalents'],
            ['available for sale securities', 'marketable securities'],
        )
        debt_series = self._p2_total_debt_series(bs_df, period)
        self._p2_plot_grouped_series(
            self.p2_simple_charts[4],
            self.p2_simple_legend_bars[4],
            [cash_series, debt_series],
            [-0.25, +0.25],
            [
                (self.theme_color('accent_positive'), self.theme_color('text_secondary'), 'Cash'),
                (self.theme_color('accent_negative'), self.theme_color('text_secondary'), 'Total Debt'),
            ],
        )

        sga_series = self._p2_extract_statement_series(fin_df, ['selling general', 'general and administrative'], period)
        rd_series = self._p2_extract_statement_series(fin_df, ['research and development'], period)
        self._p2_plot_grouped_series(
            self.p2_simple_charts[5],
            self.p2_simple_legend_bars[5],
            [sga_series, rd_series],
            [-0.25, +0.25],
            [
                (self.theme_series_color(0), self.theme_color('text_secondary'), 'SG&A'),
                (self.theme_series_color(1), self.theme_color('text_secondary'), 'R&D'),
            ],
        )

    def _p2_render_custom_charts(self, data: Any, period: Any) -> None:
        """Render the Custom Fundamentals configuration."""
        widgets = list(getattr(self, 'p2_custom_panel_widgets', []))
        descriptors = list(getattr(self, 'p2_custom_panel_descriptors', []))
        for widget_info, descriptor in zip(widgets, descriptors):
            self._p2_render_custom_panel(widget_info, descriptor, data, period)
