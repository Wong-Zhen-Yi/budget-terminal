from __future__ import annotations
from typing import Any
from ..compat import *

class FundamentalsRenderMixin:

    def update_page2(self, data: Any, *, update_collection_info: bool=True, status_text: str | None=None) -> Any:
        """Update page2."""
        self.p2_current_data = data
        ticker = data['ticker']
        info = data['info']
        source = self._p2_source_label(data) if hasattr(self, '_p2_source_label') else 'yfinance only'
        if update_collection_info:
            sec = data.get('sec') if isinstance(data.get('sec'), dict) else {}
            collection_sources = ['SEC EDGAR', 'yfinance'] if sec.get('statements_available') else ['yfinance']
            self._set_data_collection_info(collection_sources)
        self.set_status_text(
            self.p2_status_lbl,
            status_text or f'{ticker}  |  source: {source}',
            status='positive',
        )
        self.p2_analyze_btn.setEnabled(True)
        name = info.get('longName') or ticker
        sector = info.get('sector') or 'N/A'
        industry = info.get('industry') or 'N/A'
        exchange = info.get('exchange') or ''
        currency = info.get('currency') or 'USD'
        self.p2_name_lbl.setText(name)
        self.p2_info_lbl.setText(f'{exchange}  |  {sector}  |  {industry}  |  {currency}')
        website = info.get('website') or ''
        self.p2_website_url = website
        self.p2_website_btn.setVisible(bool(website))
        ir = info.get('irWebsite') or ''
        if not ir:
            ir = f'https://www.google.com/search?q={ticker}+investor+relations'
        self.p2_ir_url = ir
        self.p2_ir_btn.setVisible(True)

        def sg(key: Any) -> Any:
            """Handle sg."""
            v = info.get(key)
            return None if v is None or v == 'N/A' else v

        def reported_flow(family: str, aliases: list[str]) -> float | None:
            quarterly = self._p2_statement_frame(data, family, 'quarterly')
            values, _, columns = self._p2_extract_statement_series(quarterly, aliases, 'quarterly')
            if len(values) >= 4 and len(columns) >= 4:
                latest_values = values[-4:]
                latest_columns = columns[-4:]
                try:
                    dates = sorted(pd.Timestamp(column).normalize() for column in latest_columns)
                    gaps = [(dates[index + 1] - dates[index]).days for index in range(3)]
                except (TypeError, ValueError):
                    gaps = []
                if len(gaps) == 3 and all(50 <= gap <= 140 for gap in gaps):
                    return float(sum(latest_values))
            annual = self._p2_statement_frame(data, family, 'annual')
            annual_values, _, _ = self._p2_extract_statement_series(annual, aliases, 'annual')
            return float(annual_values[-1]) if annual_values else None

        def reported_instant(aliases: list[str]) -> float | None:
            for period in ('quarterly', 'annual'):
                frame = self._p2_statement_frame(data, 'balance_sheet', period)
                values, _, _ = self._p2_extract_statement_series(frame, aliases, period)
                if values:
                    return float(values[-1])
            return None

        def fmt_ratio(v: Any, suffix: Any='x', decimals: Any=2) -> Any:
            """Handle fmt ratio."""
            if v is None:
                return 'N/A'
            try:
                return f'{float(v):.{decimals}f}{suffix}'
            except Exception:
                return 'N/A'

        def calc_peg() -> Any:
            """Calculate PEG from P/E and earnings growth when possible."""
            growth = sg('earningsGrowth')
            if growth in (None, 0):
                return sg('pegRatio')
            pe_value = sg('forwardPE')
            if pe_value is None:
                pe_value = sg('trailingPE')
            try:
                growth_pct = float(growth) * 100
                pe_num = float(pe_value)
            except Exception:
                return sg('pegRatio')
            if growth_pct <= 0:
                return sg('pegRatio')
            return pe_num / growth_pct

        def color_lbl(lbl_widget: Any, text: Any) -> None:
            """Handle color lbl."""
            lbl_widget.setText(text)
            try:
                raw = text.replace('x', '').replace('%', '').replace('B', '').replace('M', '').replace('T', '').replace('K', '')
                num = float(raw)
                color = '#80ff80' if num >= 0 else '#ff6060'
            except Exception:
                color = 'white'
            lbl_widget.setStyleSheet(f'font-size: 17px; font-weight: bold; color: {color};')
        pe = sg('trailingPE')
        fpe = sg('forwardPE')
        ps = sg('priceToSalesTrailing12Months')
        peg = calc_peg()
        beta = sg('beta')
        mktcap = sg('marketCap')
        ev = sg('enterpriseValue')
        total_rev = reported_flow('financials', ['total revenue', 'revenue'])
        if total_rev is None:
            total_rev = sg('totalRevenue')
        fcf = reported_flow('cashflow', ['free cash flow'])
        if fcf is None:
            fcf = sg('freeCashflow')
        cash_values, _, _, _ = self._p2_resolve_curated_series(data, 'quarterly', 'cash')
        if not cash_values:
            cash_values, _, _, _ = self._p2_resolve_curated_series(data, 'annual', 'cash')
        cash_and_bonds = float(cash_values[-1]) if cash_values else None
        if cash_and_bonds is None:
            cash_and_bonds = sg('totalCash')
        total_debt = self._p2_latest_total_debt_value(data, 'quarterly')
        if total_debt is None:
            total_debt = self._p2_latest_total_debt_value(data, 'annual')
        if total_debt is None:
            total_debt = sg('totalDebt')
        ebitda = sg('ebitda')
        fcf_margin = fcf / total_rev * 100 if fcf is not None and total_rev else None
        ev_rev = ev / total_rev if ev is not None and total_rev else None
        ev_ebitda = ev / ebitda if ev is not None and ebitda else None
        net_cash = cash_and_bonds - total_debt if cash_and_bonds is not None and total_debt is not None else None
        self.p2_metric_vals['pe'].setText(fmt_ratio(pe))
        self.p2_metric_vals['fpe'].setText(fmt_ratio(fpe))
        self.p2_metric_vals['ps'].setText(fmt_ratio(ps))
        self.p2_metric_vals['peg'].setText(fmt_ratio(peg))
        color_lbl(self.p2_metric_vals['fcf_margin'], f'{fcf_margin:.1f}%' if fcf_margin is not None else 'N/A')
        self.p2_metric_vals['ev_rev'].setText(fmt_ratio(ev_rev))
        self.p2_metric_vals['ev_ebitda'].setText(fmt_ratio(ev_ebitda))
        color_lbl(self.p2_metric_vals['net_cash'], fmt_num(net_cash) if net_cash is not None else 'N/A')
        self.p2_metric_vals['beta'].setText(fmt_ratio(beta, suffix=''))
        self.p2_metric_vals['mktcap'].setText(fmt_num(mktcap) if mktcap is not None else 'N/A')
        self._on_period_toggle()
        self._p2_render_sec_filings(data)
        QTimer.singleShot(0, self._p2_relayout_charts)
        if hasattr(self, '_p2_save_session_snapshot'):
            self._p2_save_session_snapshot()

    def _p2_render_sec_filings(self, data: Any) -> None:
        """Render compact filing metadata and a clear SEC fallback state."""
        if not hasattr(self, 'p2_filings_table'):
            return
        payload = data if isinstance(data, dict) else {}
        sec = payload.get('sec') if isinstance(payload.get('sec'), dict) else {}
        filings = sec.get('filings') if isinstance(sec.get('filings'), list) else []
        self.p2_filings = list(filings)
        self.p2_filings_table.setSortingEnabled(False)
        self.p2_filings_table.setRowCount(len(filings))
        for row, filing in enumerate(filings):
            entry = filing if isinstance(filing, dict) else {}
            description = str(entry.get('description') or '').strip()
            items = str(entry.get('items') or '').strip()
            detail = ' | '.join(value for value in (description, items) if value)
            values = (
                entry.get('form'),
                entry.get('filed_date'),
                entry.get('report_period'),
                detail,
                entry.get('accession_number'),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(entry.get('document_url') or ''))
                self.p2_filings_table.setItem(row, column, item)
        self.p2_filings_table.setSortingEnabled(True)
        if filings:
            self.p2_filings_table.sortItems(1, Qt.SortOrder.DescendingOrder)

        warnings = sec.get('warnings') if isinstance(sec.get('warnings'), list) else []
        warning = str(warnings[0]) if warnings else ''
        if sec.get('available'):
            cik = str(sec.get('cik') or '').lstrip('0') or 'N/A'
            freshness = str(sec.get('freshness') or 'live')
            status = f'{len(filings)} recent SEC filings | CIK {cik} | {freshness}'
            if warning:
                status = f'{status} | {warning}'
        else:
            status = warning or 'SEC statements are unavailable for this ticker; Yahoo data remains active.'
        self.p2_filings_status.setText(status)
        self._p2_filter_filings()
