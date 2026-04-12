from __future__ import annotations
from typing import Any
from ..compat import *

class FundamentalsRenderMixin:

    def update_page2(self, data: Any, *, update_collection_info: bool=True, status_text: str | None=None) -> Any:
        """Update page2."""
        self.p2_current_data = data
        ticker = data['ticker']
        info = data['info']
        source = 'Alpha Vantage' if data.get('av_used') else 'yfinance'
        if update_collection_info:
            self._set_data_collection_info([source])
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
            lbl_widget.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {color};')
        pe = sg('trailingPE')
        fpe = sg('forwardPE')
        ps = sg('priceToSalesTrailing12Months')
        peg = calc_peg()
        beta = sg('beta')
        mktcap = sg('marketCap')
        ev = sg('enterpriseValue')
        total_rev = sg('totalRevenue')
        fcf = sg('freeCashflow')
        total_cash = sg('totalCash')
        total_debt = sg('totalDebt')
        if total_debt is None:
            total_debt = self._p2_latest_total_debt_value(data, 'quarterly')
        if total_debt is None:
            total_debt = self._p2_latest_total_debt_value(data, 'annual')
        ebitda = sg('ebitda')
        fcf_margin = fcf / total_rev * 100 if fcf is not None and total_rev else None
        ev_rev = ev / total_rev if ev is not None and total_rev else None
        ev_ebitda = ev / ebitda if ev is not None and ebitda else None
        net_cash = total_cash - total_debt if total_cash is not None and total_debt is not None else None
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
        QTimer.singleShot(0, self._p2_relayout_charts)
        if hasattr(self, '_p2_save_session_snapshot'):
            self._p2_save_session_snapshot()
