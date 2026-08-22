from __future__ import annotations
from typing import Any
from ..compat import *
from ..services.fundamentals_compare import (
    align_series_by_label,
    column_sort_key,
    compute_growth,
    index_series_values,
    series_bar_geometry,
    trim_columns,
)

# Balance sheet rows that make up "Cash and Bonds". These are matched exactly rather than by
# substring: 'short term investments' is contained in the combined row name, and the quarterly
# branch of _p2_extract_statement_series ranks substring hits by column coverage ahead of key
# order, so a loose match silently resolves the cash row twice.
_P2_CASH_COMBINED_KEYS = ['cash cash equivalents and short term investments']
_P2_CASH_EQUIVALENT_KEYS = ['cash and cash equivalents', 'cash equivalents', 'cash financial']
_P2_SHORT_TERM_INVESTMENT_KEYS = [
    'other short term investments',
    'marketable securities current',
    'short term investments',
]
_P2_LONG_TERM_INVESTMENT_KEYS = [
    'available for sale securities',
    'marketable securities noncurrent',
    'long term investments',
]

# Above this many bars a compact card cannot fit readable value labels, and the collision layout
# that places them is superlinear in bar count. Two full series of quarters is the practical edge.
P2_COMPACT_ANNOTATION_LIMIT = 32

# The six fixed overview charts, as (title, ((series key, series label), ...)). Order matters: it is
# the order of the chart cards built by init_page2.
_P2_OVERVIEW_CHARTS = (
    ('Revenue', (('revenue', 'Revenue'),)),
    ('Net Income', (('net_income', 'Net Income'),)),
    ('Cash Flow', (('operating_cf', 'Operating CF'), ('free_cf', 'Free CF'))),
    ('Shares Outstanding', (('shares', 'Shares Outstanding'),)),
    ('Cash and Bonds & Total Debt', (('cash', 'Cash and Bonds'), ('debt', 'Total Debt'))),
    ('Operating Expenses', (('sga', 'SG&A'), ('rd', 'R&D'))),
)


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
                'label': 'Cash and Bonds',
                'kind': 'cash_and_bonds',
                'family': 'balance_sheet',
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
                'label': 'Net Cash & Bonds',
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

        if period == 'quarterly':
            candidates = []
            seen_rows = set()
            ordered_cols = self._p2_ordered_statement_cols(df)
            recent_cols = ordered_cols[-16:]
            for key_index, key in enumerate(keys):
                key_text = str(key or '').strip().lower()
                exact_row = idx_lower.get(key_text)
                if exact_row is not None and exact_row not in seen_rows:
                    candidates.append((exact_row, True, key_index))
                    seen_rows.add(exact_row)
                for low, orig in idx_lower.items():
                    if key_text and key_text in low and orig not in seen_rows:
                        candidates.append((orig, False, key_index))
                        seen_rows.add(orig)

            def _coverage(candidate: Any) -> tuple[int, int, int, int]:
                row, exact, key_index = candidate
                valid_positions = []
                for position, column in enumerate(recent_cols):
                    try:
                        if not pd.isna(float(df.at[row, column])):
                            valid_positions.append(position)
                    except Exception:
                        continue
                latest_position = valid_positions[-1] if valid_positions else -1
                return (len(valid_positions), latest_position, int(exact), -key_index)

            for row, _exact, _key_index in sorted(candidates, key=_coverage, reverse=True):
                result = _extract(row)
                if result:
                    return result
            return ([], [], [])

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

    def _p2_exact_statement_row(self, df: Any, keys: Any) -> Any:
        """Return the first statement row matching one key exactly, ignoring case."""
        idx_lower = {str(row).lower(): row for row in getattr(df, 'index', [])}
        for key in keys:
            row = idx_lower.get(str(key or '').strip().lower())
            if row is not None:
                return row
        return None

    def _p2_cash_and_bonds_series(self, df: Any, period: Any) -> Any:
        """Resolve cash, equivalents, and short and long term marketable securities."""
        if df is None or df.empty:
            return ([], [], [])
        combined_row = self._p2_exact_statement_row(df, _P2_CASH_COMBINED_KEYS)
        cash_row = self._p2_exact_statement_row(df, _P2_CASH_EQUIVALENT_KEYS)
        short_term_row = self._p2_exact_statement_row(df, _P2_SHORT_TERM_INVESTMENT_KEYS)
        long_term_row = self._p2_exact_statement_row(df, _P2_LONG_TERM_INVESTMENT_KEYS)
        values, labels, cols = ([], [], [])
        for column in self._p2_ordered_statement_cols(df):

            def cell(row: Any) -> float | None:
                """Return one numeric cell, or None when the row is absent or blank."""
                if row is None:
                    return None
                try:
                    value = float(df.at[row, column])
                except Exception:
                    return None
                return None if pd.isna(value) else value

            # The combined row already bundles cash with short term investments, so it is used
            # on its own to avoid double counting the short term leg.
            base = cell(combined_row)
            if base is None:
                cash = cell(cash_row)
                short_term = cell(short_term_row)
                if cash is None and short_term is None:
                    continue
                base = (cash or 0.0) + (short_term or 0.0)
            values.append(base + (cell(long_term_row) or 0.0))
            labels.append(self._p2_col_label(column, period))
            cols.append(column)
        return (values, labels, cols) if values else ([], [], [])

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
        if spec.get('kind') == 'cash_and_bonds':
            values, labels, cols = self._p2_cash_and_bonds_series(frame, period)
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
        while bar_layout.count():
            item = bar_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    def _p2_solid_bars(self, x_values: Any, heights: Any, color: Any, width: float=0.7, *, filled: bool=True) -> Any:
        """Build one bar series for a Fundamentals plot, solid or hollow.

        The hollow variant keeps the metric's hue while marking the compare ticker. Tinting the
        color instead would lower contrast, which reads as 'less important' rather than
        'different company' and nearly disappears on the dark themes.
        """
        brush = pg.mkBrush(color) if filled else pg.mkBrush(None)
        pen = pg.mkPen(color, width=1 if filled else 2)
        return pg.BarGraphItem(x=x_values, height=heights, width=width, brush=brush, pen=pen)

    def _p2_register_chart_hover(self, plot: Any, *, owner: Any=None) -> None:
        """Attach one retained mouse proxy to a Fundamentals plot."""
        proxy = pg.SignalProxy(
            plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=partial(self._p2_on_chart_mouse_moved, plot),
        )
        if owner is not None:
            proxies = list(getattr(owner, '_p2_hover_proxies', []))
            proxies.append(proxy)
            owner._p2_hover_proxies = proxies
        else:
            self.p2_chart_hover_proxies.append(proxy)

    def _p2_on_chart_mouse_moved(self, plot: Any, event: Any) -> None:
        """Show contextual data only while the pointer is inside a rendered bar."""
        position = event[0] if isinstance(event, (tuple, list)) else event
        if position is None or not plot.sceneBoundingRect().contains(position):
            plot._p2_hover_key = None
            QToolTip.hideText()
            return
        point = plot.getPlotItem().vb.mapSceneToView(position)
        match = None
        for region in list(getattr(plot, '_p2_bar_regions', [])):
            value = float(region['value'])
            low, high = sorted((0.0, value))
            half_width = float(region['width']) / 2.0
            if region['x'] - half_width <= point.x() <= region['x'] + half_width and low <= point.y() <= high:
                match = region
                break
        if match is None:
            plot._p2_hover_key = None
            QToolTip.hideText()
            return
        hover_key = match['key']
        if getattr(plot, '_p2_hover_key', None) == hover_key:
            return
        plot._p2_hover_key = hover_key
        QToolTip.showText(pg.QtGui.QCursor.pos(), self._p2_bar_tooltip_text(match), plot)

    def _p2_growth_text(self, growth: Any) -> str:
        """Format one chart growth value consistently."""
        if growth is None:
            return '—'
        try:
            value = float(growth)
        except (TypeError, ValueError):
            return '—'
        sign = '+' if value >= 0 else ''
        return f'{sign}{value:.1f}%'

    def _p2_bar_tooltip_text(self, region: Any) -> str:
        """Build the compact-chart hover text for one bar."""
        raw_value = region.get('raw_value', region.get('value'))
        lines = [
            str(region.get('period', '') or ''),
            f'{region.get("series", "Value")}: {fmt_num(raw_value)}',
        ]
        if region.get('indexed'):
            base_period = str(region.get('indexed_base_period', '') or '')
            suffix = f' ({base_period} = 100)' if base_period else ''
            lines.append(f'Index: {float(region.get("value", 0.0)):.0f}{suffix}')
        # Naming the baseline period makes the active growth basis unambiguous without having to
        # look back at the QoQ/YoY toggle.
        baseline = str(region.get('growth_baseline', '') or '')
        label = f'Growth vs {baseline}' if baseline else 'Growth'
        lines.append(f'{label}: {self._p2_growth_text(region.get("growth"))}')
        return '\n'.join(lines)

    def _p2_chart_model(
        self,
        title: str,
        period: str,
        series_specs: list[dict[str, Any]],
        *,
        period_count: int | None=None,
        indexed: bool=False,
        growth_basis: str | None=None,
    ) -> dict[str, Any]:
        """Normalize one overview into a shared compact/fullscreen chart model."""
        limit = self._p2_period_count() if period_count is None else period_count
        basis = self._p2_growth_basis() if growth_basis is None else growth_basis
        all_columns = []
        labels_by_column = {}
        normalized_specs = []
        for raw_spec in series_specs:
            values, labels, columns = raw_spec.get('data', ([], [], []))
            points = []
            for point_index, (value, label, column) in enumerate(zip(values, labels, columns)):
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue
                if pd.isna(numeric_value):
                    continue
                if column not in all_columns:
                    all_columns.append(column)
                labels_by_column[column] = str(label)
                points.append({
                    'column': column,
                    'period': str(label),
                    'value': numeric_value,
                    'raw_value': numeric_value,
                    'point_index': point_index,
                    'indexed': False,
                })
            # Growth needs the whole series and runs before the trim below: a year-ago baseline can
            # sit several periods before the oldest one the chart ends up showing.
            growth_pairs = compute_growth(
                [point['period'] for point in points],
                [point['value'] for point in points],
                basis=basis,
            )
            for point, (growth, baseline_label) in zip(points, growth_pairs):
                point['growth'] = growth
                point['growth_baseline'] = baseline_label
            normalized_specs.append({
                'name': str(raw_spec.get('name', title) or title),
                'legend_name': str(raw_spec.get('legend_name', '') or ''),
                'color': raw_spec.get('color') or self.theme_series_color(0),
                'label_color': raw_spec.get('label_color') or self.theme_color('text_secondary'),
                'offset': float(raw_spec.get('offset', 0.0) or 0.0),
                'width': float(raw_spec.get('width', 0.7) or 0.7),
                'filled': bool(raw_spec.get('filled', True)),
                'points': points,
            })
        try:
            ordered_columns = sorted(all_columns, key=column_sort_key)
        except TypeError:
            ordered_columns = all_columns
        available_columns = len(ordered_columns)
        trimmed_columns = trim_columns(ordered_columns, limit)
        if len(trimmed_columns) != available_columns:
            ordered_columns = trimmed_columns
            visible_columns = set(ordered_columns)
            for series in normalized_specs:
                series['points'] = [
                    point for point in series['points']
                    if point['column'] in visible_columns
                ]
        # Rebasing happens after the trim so the base is the oldest *visible* period. Growth stays
        # as computed above: it is scale-invariant, and the oldest visible bar keeps a real growth
        # number derived from a now-off-chart period.
        if indexed:
            for series in normalized_specs:
                points = series['points']
                indexed_values, base = index_series_values([point['value'] for point in points])
                for point, indexed_value in zip(points, indexed_values):
                    point['value'] = indexed_value
                    point['indexed'] = True
                series['indexed_base'] = base
                series['indexed_base_period'] = points[0]['period'] if points else ''
        column_positions = {column: index for index, column in enumerate(ordered_columns)}
        for series_index, series in enumerate(normalized_specs):
            for point in series['points']:
                point['x'] = column_positions[point['column']] + series['offset']
                point['key'] = (title, series_index, point['point_index'])
        return {
            'title': title,
            'period': period,
            'period_count': limit,
            'available_columns': available_columns,
            'indexed': bool(indexed),
            'growth_basis': basis,
            'columns': ordered_columns,
            'labels': [labels_by_column.get(column, str(column)) for column in ordered_columns],
            'series': normalized_specs,
        }

    def _p2_chart_model_from_entries(
        self,
        title: str,
        period: str,
        entries: list[dict[str, Any]],
        *,
        period_count: int | None=None,
        indexed: bool=False,
        growth_basis: str | None=None,
    ) -> dict[str, Any]:
        """Lay out N series evenly and build the shared chart model.

        Entries carry no geometry. Empty series are dropped before the layout is computed, so a
        chart whose second metric has no reported rows draws its remaining bars centred on the
        period tick instead of leaving a permanent gap.
        """
        populated = [entry for entry in entries if list((entry.get('data') or ([], [], []))[0])]
        geometry = series_bar_geometry(len(populated))
        text_color = self.theme_color('text_secondary')
        specs = []
        for entry, (offset, width) in zip(populated, geometry):
            specs.append({
                'name': entry.get('name', title),
                'legend_name': entry.get('legend_name', ''),
                'data': entry.get('data', ([], [], [])),
                'color': entry.get('color'),
                'label_color': entry.get('label_color') or text_color,
                'filled': entry.get('filled', True),
                'offset': offset,
                'width': width,
            })
        return self._p2_chart_model(
            title,
            period,
            specs,
            period_count=period_count,
            indexed=indexed,
            growth_basis=growth_basis,
        )

    def _p2_chart_model_has_data(self, model: Any) -> bool:
        """Return whether a chart model contains at least one visible bar."""
        return any(
            point.get('value') not in (None, 0)
            for series in (model or {}).get('series', [])
            for point in series.get('points', [])
        )

    def _p2_set_plot_y_range(self, pw: Any, values: Any, *, annotation_profile: str='compact') -> None:
        """Apply a comfortable Y-range around a bar series."""
        nonzero = [value for value in values if value != 0]
        if not nonzero:
            return
        y_max = max(nonzero) if max(nonzero) > 0 else 0
        y_min = min(nonzero) if min(nonzero) < 0 else 0
        data_range = abs(y_max - y_min) or abs(y_max or y_min)
        is_fullscreen = annotation_profile == 'fullscreen'
        pad_ratio = 0.32 if is_fullscreen else 0.24
        value_ratio = 0.36 if is_fullscreen else 0.30
        pad_top = max(abs(y_max) * value_ratio, data_range * pad_ratio) if y_max >= 0 else 0
        pad_bottom = max(abs(y_min) * value_ratio, data_range * pad_ratio) if y_min <= 0 else 0
        pw.setYRange(y_min - pad_bottom, y_max + pad_top, padding=0)

    def _p2_set_plot_ticks(self, pw: Any, labels: Any, *, fullscreen: bool=False) -> None:
        """Apply statement-period labels to the plot X-axis."""
        count = len(labels)
        if fullscreen:
            tick_stride = 1
        else:
            slot_width = max(1.0, float(pw.width()) / max(1, count))
            widest_label = max((len(str(label)) for label in labels), default=0)
            target_width = max(26.0, widest_label * 5.5)
            tick_stride = max(1, int(math.ceil(target_width / slot_width)))
        tick_indices = self._p2_tick_indices(count, tick_stride)
        ticks = [(index, labels[index]) for index in tick_indices]
        pw.getAxis('bottom').setTicks([ticks])
        pw.getAxis('bottom').setStyle(tickFont=pg.QtGui.QFont('Arial', 7))

    def _p2_tick_indices(self, count: int, stride: int) -> list[int]:
        """Return spaced tick indices while keeping the newest period visible."""
        if count <= 0:
            return []
        safe_stride = max(1, int(stride))
        indices = list(range(0, count, safe_stride))
        last_index = count - 1
        if last_index not in indices:
            if indices and last_index - indices[-1] < safe_stride:
                indices[-1] = last_index
            else:
                indices.append(last_index)
        return indices

    def _p2_set_plot_x_range(self, pw: Any, count: int, *, annotation_profile: str | None='compact') -> None:
        """Apply a fixed X-range for one bar chart."""
        if annotation_profile == 'compact':
            edge_padding = 1.35
        elif annotation_profile == 'fullscreen':
            edge_padding = 1.0
        else:
            edge_padding = 0.6
        pw.setXRange(-edge_padding, max(0, count - 1) + edge_padding, padding=0)

    def _p2_render_chart_model(
        self,
        pw: Any,
        legend_bar: Any,
        model: dict[str, Any],
        *,
        fullscreen: bool=False,
    ) -> None:
        """Render one shared chart model in compact or fullscreen mode."""
        pw.clear()
        QToolTip.hideText()
        pw._p2_hover_key = None
        pw._p2_bar_regions = []
        pw._p2_annotation_items = []
        self._p2_clear_legend_bar(legend_bar)
        series_list = list(model.get('series', []))
        labels = list(model.get('labels', []))
        # Four compare series carry roughly 320px of legend text, which does not fit beside the
        # title in a compact card. Fall back to the ticker alone there and keep full names
        # fullscreen, where there is room.
        compact_legend = not fullscreen and len(series_list) > 2
        if len(series_list) > 1:
            bar_layout = legend_bar.layout()
            if bar_layout is not None:
                for series in series_list:
                    swatch = QLabel()
                    swatch.setFixedSize(12, 12)
                    if series.get('filled', True):
                        swatch.setStyleSheet(f'background: {series["color"]}; border-radius: 2px;')
                    else:
                        swatch.setStyleSheet(
                            f'background: transparent; border: 2px solid {series["color"]}; border-radius: 2px;'
                        )
                    label_text = str(series.get('legend_name') or series['name']) if compact_legend else series['name']
                    text = QLabel(label_text)
                    text.setStyleSheet(
                        f'color: {self.theme_color("text_primary")}; font-size: 11px; background: transparent;'
                    )
                    bar_layout.addWidget(swatch)
                    bar_layout.addWidget(text)
                    bar_layout.addSpacing(12)
        left_axis = pw.getAxis('left')
        if left_axis is not None:
            left_axis.p2_index_mode = bool(model.get('indexed'))
        if not labels:
            pw.getAxis('bottom').setTicks([[]])
            pw.getPlotItem().vb.autoRange()
            return
        all_values = []
        for series_index, series in enumerate(series_list):
            points = list(series.get('points', []))
            if not points:
                continue
            x_values = [point['x'] for point in points]
            values = [point['value'] for point in points]
            pw.addItem(self._p2_solid_bars(
                x_values,
                values,
                series['color'],
                width=series['width'],
                filled=series.get('filled', True),
            ))
            for point in points:
                region = {
                    **point,
                    'series': series['name'],
                    'width': series['width'],
                    'label_color': series['label_color'],
                    'series_index': series_index,
                    'indexed_base_period': series.get('indexed_base_period', ''),
                }
                pw._p2_bar_regions.append(region)
            all_values.extend(values)
        self._p2_set_plot_ticks(pw, labels, fullscreen=fullscreen)
        annotation_profile = 'fullscreen' if fullscreen else 'compact'
        self._p2_set_plot_x_range(pw, len(labels), annotation_profile=annotation_profile)
        self._p2_set_plot_y_range(pw, all_values, annotation_profile=annotation_profile)
        self._p2_create_chart_annotations(pw, profile=annotation_profile)

    def _p2_create_chart_annotations(self, pw: Any, *, profile: str) -> None:
        """Create every value/growth label for a compact or fullscreen plot."""
        font_size = 9 if profile == 'fullscreen' else 7
        font = pg.QtGui.QFont('Arial', font_size, pg.QtGui.QFont.Weight.Bold)
        if profile == 'compact':
            font.setStretch(pg.QtGui.QFont.Stretch.Condensed)
        # Compact label placement is superlinear in bar count and reruns on every resize. Past
        # roughly two full series of quarters the labels no longer fit anyway, so hover carries
        # the detail instead. Fullscreen has the room and keeps every label.
        if profile == 'compact' and len(pw._p2_bar_regions) > P2_COMPACT_ANNOTATION_LIMIT:
            pw._p2_annotation_items = []
            pw._p2_annotation_profile = profile
            return
        annotations = []
        for region in pw._p2_bar_regions:
            if region['value'] == 0:
                continue
            value_text = f'{region["value"]:.0f}' if region.get('indexed') else str(fmt_num(region['value']))
            growth_text = self._p2_growth_text(region.get('growth'))
            text = f'{value_text}\n{growth_text}'
            anchor = (0.5, 1.0 if region['value'] >= 0 else 0.0)
            item = pg.TextItem(text=text, color=region['label_color'], anchor=anchor)
            item.setFont(font)
            if profile == 'compact':
                item.textItem.document().setDocumentMargin(0.0)
                item.updateTextPos()
            item.setZValue(20)
            item.setPos(region['x'], region['value'])
            leader = pg.PlotDataItem(pen=pg.mkPen(region['label_color'], width=1))
            leader.setZValue(10)
            leader.setVisible(False)
            pw.addItem(leader)
            pw.addItem(item)
            annotations.append({'item': item, 'leader': leader, 'region': region})
        pw._p2_annotation_items = annotations
        pw._p2_annotation_profile = profile
        QTimer.singleShot(0, partial(self._p2_layout_chart_annotations, pw))

    def _p2_layout_chart_annotations(self, pw: Any) -> None:
        """Place chart labels into measured, non-overlapping vertical lanes."""
        annotations = list(getattr(pw, '_p2_annotation_items', []))
        if not annotations or not pw.isVisible():
            return
        view_box = pw.getPlotItem().vb
        scene_rect = view_box.sceneBoundingRect()
        if scene_rect.width() <= 0 or scene_rect.height() <= 0:
            return
        compact = getattr(pw, '_p2_annotation_profile', 'compact') == 'compact'
        if compact:
            self._p2_layout_compact_annotations(pw, annotations, scene_rect)
            return
        minimum_item_height = 20.0
        lane_gap = 4.0
        for _ in range(4):
            placed_rects = []
            view_extents = []
            ordered = sorted(
                annotations,
                key=lambda entry: (entry['region']['x'], entry['region']['series_index']),
            )
            for entry in ordered:
                item = entry['item']
                leader = entry['leader']
                region = entry['region']
                base_scene = view_box.mapViewToScene(pg.QtCore.QPointF(region['x'], region['value']))
                direction = -1.0 if region['value'] >= 0 else 1.0
                item_height = max(minimum_item_height, item.sceneBoundingRect().height())
                chosen_y = float(region['value'])
                chosen_rect = None
                chosen_lane = 0
                for lane in range(len(annotations) + 2):
                    scene_y = base_scene.y() + direction * lane * (item_height + lane_gap)
                    view_position = view_box.mapSceneToView(pg.QtCore.QPointF(base_scene.x(), scene_y))
                    item.setPos(region['x'], view_position.y())
                    candidate = item.sceneBoundingRect().adjusted(-2.0, -2.0, 2.0, 2.0)
                    if not any(candidate.intersects(existing) for existing in placed_rects):
                        chosen_y = view_position.y()
                        chosen_rect = candidate
                        chosen_lane = lane
                        break
                if chosen_rect is None:
                    chosen_rect = item.sceneBoundingRect().adjusted(-2.0, -2.0, 2.0, 2.0)
                placed_rects.append(chosen_rect)
                leader.setVisible(chosen_lane > 0)
                leader.setData([region['x'], region['x']], [region['value'], chosen_y])
                top_view = view_box.mapSceneToView(chosen_rect.topLeft()).y()
                bottom_view = view_box.mapSceneToView(chosen_rect.bottomRight()).y()
                view_extents.extend((top_view, bottom_view))
            values = [float(region['value']) for region in pw._p2_bar_regions]
            if not values or not view_extents:
                return
            current_min, current_max = view_box.viewRange()[1]
            required_min = min(min(values), min(view_extents))
            required_max = max(max(values), max(view_extents))
            span = max(1e-9, max(current_max, required_max) - min(current_min, required_min))
            maximum_label_height = max(
                (entry['item'].sceneBoundingRect().height() for entry in annotations),
                default=minimum_item_height,
            )
            view_padding = span * (maximum_label_height + lane_gap) / max(1.0, scene_rect.height())
            target_min = required_min - view_padding if required_min < current_min else current_min
            target_max = required_max + view_padding if required_max > current_max else current_max
            if target_min < current_min or target_max > current_max:
                pw.setYRange(target_min, target_max, padding=0)

    def _p2_layout_compact_annotations(self, pw: Any, annotations: Any, scene_rect: Any) -> None:
        """Keep compact labels at bar ends, displacing only actual collisions."""
        view_box = pw.getPlotItem().vb
        label_gap = 2.0
        lane_gap = 4.0
        plot_margin = 3.0
        collision_padding = 1.0
        maximum_label_height = max(
            (entry['item'].sceneBoundingRect().height() for entry in annotations),
            default=16.0,
        )
        row_height = maximum_label_height + lane_gap

        def assign_lanes(entries: Any) -> tuple[dict[int, int], int]:
            """Color overlapping horizontal intervals into stable compact lanes."""
            lane_right_edges = []
            intervals = []
            for entry in entries:
                region = entry['region']
                center = view_box.mapViewToScene(pg.QtCore.QPointF(region['x'], region['value'])).x()
                width = max(1.0, entry['item'].sceneBoundingRect().width())
                intervals.append((center - width / 2.0, center + width / 2.0, entry))
            assignments = {}
            for left, right, entry in sorted(intervals, key=lambda value: value[0]):
                lane = next(
                    (
                        index
                        for index, previous_right in enumerate(lane_right_edges)
                        if left >= previous_right + collision_padding * 2.0
                    ),
                    len(lane_right_edges),
                )
                if lane == len(lane_right_edges):
                    lane_right_edges.append(right)
                else:
                    lane_right_edges[lane] = right
                assignments[id(entry)] = lane
            return assignments, len(lane_right_edges)

        positive = [entry for entry in annotations if entry['region']['value'] >= 0]
        negative = [entry for entry in annotations if entry['region']['value'] < 0]
        positive_lanes, positive_lane_count = assign_lanes(positive)
        negative_lanes, negative_lane_count = assign_lanes(negative)
        top_reserve = positive_lane_count * row_height + plot_margin if positive else 0.0
        bottom_reserve = negative_lane_count * row_height + plot_margin if negative else 0.0
        values = [float(region['value']) for region in pw._p2_bar_regions]
        data_min = min(0.0, min(values))
        data_max = max(0.0, max(values))
        data_span = max(1e-9, data_max - data_min or abs(data_max or data_min))
        for _ in range(4):
            available_data_height = max(
                8.0,
                scene_rect.height() - top_reserve - bottom_reserve,
            )
            top_padding = data_span * top_reserve / available_data_height
            bottom_padding = data_span * bottom_reserve / available_data_height
            pw.setYRange(data_min - bottom_padding, data_max + top_padding, padding=0)

            preferred_scene_y = {}
            for entry in annotations:
                region = entry['region']
                is_positive = region['value'] >= 0
                direction = -1.0 if is_positive else 1.0
                base_scene = view_box.mapViewToScene(pg.QtCore.QPointF(region['x'], region['value']))
                preferred_scene_y[id(entry)] = base_scene.y() + direction * label_gap

            placed_rects = []
            outside_plot = False

            def place_sign(entries: Any, lanes: Any, lane_count: int, *, positive_sign: bool) -> None:
                nonlocal outside_plot
                for lane in range(lane_count):
                    lane_entries = sorted(
                        (entry for entry in entries if lanes[id(entry)] == lane),
                        key=lambda entry: entry['region']['x'],
                    )
                    for entry in lane_entries:
                        item = entry['item']
                        leader = entry['leader']
                        region = entry['region']
                        item.setAnchor((0.5, 1.0 if positive_sign else 0.0))
                        base_scene = view_box.mapViewToScene(
                            pg.QtCore.QPointF(region['x'], region['value'])
                        )
                        anchor_scene_y = preferred_scene_y[id(entry)]
                        candidate = None
                        for _ in range(len(annotations) + 1):
                            label_position = view_box.mapSceneToView(
                                pg.QtCore.QPointF(base_scene.x(), anchor_scene_y)
                            )
                            item.setPos(region['x'], label_position.y())
                            candidate = item.sceneBoundingRect().adjusted(
                                -collision_padding,
                                -collision_padding,
                                collision_padding,
                                collision_padding,
                            )
                            conflicts = [
                                existing
                                for existing in placed_rects
                                if candidate.intersects(existing)
                            ]
                            if not conflicts:
                                break
                            if positive_sign:
                                shift = max(
                                    candidate.bottom() - existing.top() + lane_gap
                                    for existing in conflicts
                                )
                                anchor_scene_y -= shift
                            else:
                                shift = max(
                                    existing.bottom() - candidate.top() + lane_gap
                                    for existing in conflicts
                                )
                                anchor_scene_y += shift
                        if candidate is None:
                            continue
                        placed_rects.append(candidate)
                        displaced = not math.isclose(
                            anchor_scene_y,
                            preferred_scene_y[id(entry)],
                            abs_tol=0.5,
                        )
                        entry['displaced'] = displaced
                        leader.setVisible(displaced)
                        leader.setData(
                            [region['x'], region['x']],
                            [region['value'], label_position.y()],
                        )
                        if not scene_rect.adjusted(
                            plot_margin,
                            plot_margin,
                            -plot_margin,
                            -plot_margin,
                        ).contains(candidate):
                            outside_plot = True

            place_sign(positive, positive_lanes, positive_lane_count, positive_sign=True)
            place_sign(negative, negative_lanes, negative_lane_count, positive_sign=False)

            collisions = any(
                left.intersects(right)
                for left_index, left in enumerate(placed_rects)
                for right in placed_rects[left_index + 1:]
            )
            if not outside_plot and not collisions:
                return
            if positive:
                top_reserve += row_height
            if negative:
                bottom_reserve += row_height

    def _p2_overview_series(self, data: Any, period: Any, *, allow_shares_fallback: bool=True) -> dict[str, tuple]:
        """Resolve every (values, labels, columns, color) series behind the six overview charts."""
        payload = data if isinstance(data, dict) else {}
        fin_df = payload.get('financials') if period == 'annual' else payload.get('quarterly_financials')
        bs_df = payload.get('balance_sheet') if period == 'annual' else payload.get('quarterly_balance_sheet')
        cf_df = payload.get('cashflow') if period == 'annual' else payload.get('quarterly_cashflow')
        info = payload.get('info') if isinstance(payload.get('info'), dict) else {}

        revenue = self._p2_resolve_curated_series(payload, period, 'revenue')
        net_income = self._p2_resolve_curated_series(payload, period, 'net_income')
        operating_cf = self._p2_extract_statement_series(
            cf_df,
            ['operating cash flow', 'cash from operations'],
            period,
        )
        free_cf = self._p2_extract_statement_series(cf_df, ['free cash flow'], period)
        shares = self._p2_extract_statement_series(
            bs_df,
            ['ordinary shares number', 'shares outstanding', 'common stock shares outstanding'],
            period,
        )
        if not shares[0] and allow_shares_fallback:
            shares_scalar = info.get('sharesOutstanding')
            if shares_scalar is not None:
                try:
                    shares = ([float(shares_scalar)], ['Current'], ['current'])
                except (TypeError, ValueError):
                    shares = ([], [], [])
        cash_series = self._p2_resolve_curated_series(payload, period, 'cash')
        debt_series = self._p2_total_debt_series(bs_df, period)
        sga_series = self._p2_extract_statement_series(
            fin_df,
            ['selling general', 'general and administrative'],
            period,
        )
        rd_series = self._p2_extract_statement_series(fin_df, ['research and development'], period)
        return {
            'revenue': (revenue[0], revenue[1], revenue[2], revenue[3]),
            'net_income': (net_income[0], net_income[1], net_income[2], net_income[3]),
            'operating_cf': (*operating_cf, self.theme_series_color(2)),
            'free_cf': (*free_cf, self.theme_series_color(3)),
            'shares': (*shares, self.theme_series_color(4)),
            'cash': (cash_series[0], cash_series[1], cash_series[2], self.theme_color('accent_positive')),
            'debt': (*debt_series, self.theme_color('accent_negative')),
            'sga': (*sga_series, self.theme_series_color(0)),
            'rd': (*rd_series, self.theme_series_color(1)),
        }

    def _p2_default_chart_models(self, data: Any, period: Any) -> list[dict[str, Any]]:
        """Build the six fixed overview models, overlaying the compare ticker when one is loaded."""
        compare_data = getattr(self, 'p2_compare_data', None)
        compare_active = isinstance(compare_data, dict) and isinstance(data, dict)
        period_count = self._p2_period_count()
        indexed = self._p2_indexed_enabled()
        growth_basis = self._p2_growth_basis()
        primary_ticker = str((data if isinstance(data, dict) else {}).get('ticker', '') or '').upper().strip()
        # A lone 'Current' shares-outstanding bar is an instantaneous value, not a period. Beside a
        # second ticker's dated bars it reads as one, so the fallback is dropped while comparing.
        sources = [(primary_ticker, self._p2_overview_series(data, period, allow_shares_fallback=not compare_active), True)]
        if compare_active:
            sources.append((
                str(compare_data.get('ticker', '') or '').upper().strip(),
                self._p2_overview_series(compare_data, period, allow_shares_fallback=False),
                False,
            ))

        models = []
        for title, metrics in _P2_OVERVIEW_CHARTS:
            entries = []
            for metric_key, metric_label in metrics:
                for ticker, series_map, filled in sources:
                    values, labels, columns, color = series_map[metric_key]
                    if compare_active:
                        # Two companies never share a fiscal calendar, so align on the rendered
                        # period label rather than the raw statement column.
                        values, labels, columns = align_series_by_label(values, labels, columns)
                    entries.append({
                        'name': f'{ticker} {metric_label}' if compare_active and ticker else metric_label,
                        'legend_name': ticker if compare_active and ticker else metric_label,
                        'data': (values, labels, columns),
                        'color': color,
                        'filled': filled,
                    })
            models.append(self._p2_chart_model_from_entries(
                title,
                period,
                entries,
                period_count=period_count,
                indexed=indexed,
                growth_basis=growth_basis,
            ))
        return models

    def _render_simple_charts(self, data: Any, period: Any) -> Any:
        """Render the fixed Default Fundamentals configuration."""
        models = self._p2_default_chart_models(data, period)
        self.p2_chart_models = models
        self._p2_rendered_compare_ticker = (
            str(getattr(self, 'p2_compare_ticker', '') or '').upper().strip()
            if self._p2_compare_active()
            else ''
        )
        for index, model in enumerate(models):
            self._p2_render_chart_model(
                self.p2_simple_charts[index],
                self.p2_simple_legend_bars[index],
                model,
            )
        for button in getattr(self, 'p2_expand_buttons', []):
            button.setEnabled(True)
        # Record the geometry these plots were actually drawn at, so _p2_refresh_chart_density can
        # tell a real reflow from a redundant rerender.
        self._p2_chart_render_geometry = self._p2_chart_geometry_signature()
        self._p2_sync_periods_availability()
