from __future__ import annotations
import numpy as np
from typing import Any
from ..compat import *


@dataclass
class ScreenerResult:
    ticker: str = ''
    price: Any = None
    change: Any = None
    mkt_cap: Any = None
    rsi: Any = None
    trend: str | None = None
    trend_slope: float | None = None


_MKTCAP_RANGES = [
    ('Any', None, None),
    ('Mega (>200B)', 200_000_000_000, None),
    ('Large (10B-200B)', 10_000_000_000, 200_000_000_000),
    ('Mid (2B-10B)', 2_000_000_000, 10_000_000_000),
    ('Small (300M-2B)', 300_000_000, 2_000_000_000),
    ('Micro (<300M)', None, 300_000_000),
]

_RSI_RANGES = [
    ('Any', None, None),
    ('0 - 10', 0, 10),
    ('10 - 20', 10, 20),
    ('20 - 30', 20, 30),
    ('30 - 40', 30, 40),
    ('40 - 50', 40, 50),
    ('50 - 60', 50, 60),
    ('60 - 70', 60, 70),
    ('70 - 80', 70, 80),
    ('80 - 90', 80, 90),
    ('90 - 100', 90, 100),
]

_TREND_OPTIONS = ['Any', 'Upward', 'Consolidating', 'Downward']
_TREND_THRESHOLD = 0.05  # daily slope as % of mean price

_TIMEFRAME_OPTIONS = [
    ('1H', '5d', '1h'),
    ('1D', '1mo', '1d'),
    ('1W', '6mo', '1wk'),
]


def _compute_rsi(closes: Any, period: int = 14) -> float | None:
    """Compute RSI from a series of closing prices."""
    if closes is None or len(closes) < period + 1:
        return None
    deltas = closes.diff().dropna()
    if len(deltas) < period:
        return None
    gains = deltas.clip(lower=0)
    losses = (-deltas.clip(upper=0))
    avg_gain = gains.rolling(window=period, min_periods=period).mean().iloc[-1]
    avg_loss = losses.rolling(window=period, min_periods=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_linreg_trend(closes: Any, threshold: float = _TREND_THRESHOLD) -> tuple[str, float] | tuple[None, None]:
    """Classify trend via linear regression slope on closing prices.

    Returns (label, slope_pct) where slope_pct is the daily slope
    as a percentage of the mean price.
    """
    if closes is None or len(closes) < 5:
        return None, None
    values = closes.dropna().values.astype(float)
    if len(values) < 5:
        return None, None
    x = np.arange(len(values), dtype=float)
    slope, _ = np.polyfit(x, values, 1)
    mean_price = np.mean(values)
    if mean_price == 0:
        return None, None
    slope_pct = (slope / mean_price) * 100.0
    if slope_pct > threshold:
        return 'Upward', slope_pct
    elif slope_pct < -threshold:
        return 'Downward', slope_pct
    return 'Consolidating', slope_pct


class ScreenerMixin:

    def init_page12(self) -> None:
        """Build the Screener page UI."""
        self._p12_results: list[ScreenerResult] = []
        self._p12_fetch_in_progress = False

        layout = QVBoxLayout(self.page12)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # -- Title row --
        title_row = QHBoxLayout()
        title_lbl = QLabel('<b>Stock Screener</b>')
        self.set_theme_role(title_lbl, 'page_title')
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        layout.addLayout(title_row)

        # -- Filter row --
        filter_frame = QFrame()
        filter_frame.setStyleSheet(
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        filter_layout.setSpacing(12)

        # Timeframe
        tf_label = QLabel('Timeframe:')
        tf_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self.p12_timeframe_combo = QComboBox()
        self.p12_timeframe_combo.setMinimumWidth(80)
        for label, _, _ in _TIMEFRAME_OPTIONS:
            self.p12_timeframe_combo.addItem(label)
        self.p12_timeframe_combo.setCurrentIndex(1)  # default to 1D
        filter_layout.addWidget(tf_label)
        filter_layout.addWidget(self.p12_timeframe_combo)

        filter_layout.addSpacing(20)

        # Market Cap filter
        mktcap_label = QLabel('Market Cap:')
        mktcap_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self.p12_mktcap_combo = QComboBox()
        self.p12_mktcap_combo.setMinimumWidth(160)
        for label, _, _ in _MKTCAP_RANGES:
            self.p12_mktcap_combo.addItem(label)
        filter_layout.addWidget(mktcap_label)
        filter_layout.addWidget(self.p12_mktcap_combo)

        filter_layout.addSpacing(20)

        # RSI filter
        rsi_label = QLabel('RSI (14):')
        rsi_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self.p12_rsi_combo = QComboBox()
        self.p12_rsi_combo.setMinimumWidth(120)
        for label, _, _ in _RSI_RANGES:
            self.p12_rsi_combo.addItem(label)
        filter_layout.addWidget(rsi_label)
        filter_layout.addWidget(self.p12_rsi_combo)

        filter_layout.addSpacing(20)

        # Linear regression filter
        trend_label = QLabel('Linear Regression:')
        trend_label.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        self.p12_trend_combo = QComboBox()
        self.p12_trend_combo.setMinimumWidth(140)
        for label in _TREND_OPTIONS:
            self.p12_trend_combo.addItem(label)
        filter_layout.addWidget(trend_label)
        filter_layout.addWidget(self.p12_trend_combo)

        filter_layout.addSpacing(20)

        # Scan button
        self.p12_scan_btn = QPushButton('Scan')
        self.set_theme_variant(self.p12_scan_btn, 'accent')
        self.p12_scan_btn.setMinimumHeight(30)
        self.p12_scan_btn.setMinimumWidth(100)
        self.p12_scan_btn.clicked.connect(self._p12_run_scan)
        filter_layout.addWidget(self.p12_scan_btn)

        filter_layout.addStretch()
        layout.addWidget(filter_frame)

        # -- Status --
        self.p12_status_lbl = QLabel('Ready — press Scan to search')
        self.set_theme_role(self.p12_status_lbl, 'status_muted')
        self.p12_status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.p12_status_lbl)

        # -- Results table --
        self.p12_table = QTableWidget(0, 7)
        self.p12_table.setHorizontalHeaderLabels(['Ticker', 'Price', 'Chg %', 'Market Cap', 'RSI (14)', 'Lin. Reg.', 'Slope %/d'])
        hh = self.p12_table.horizontalHeader()
        hh.setMinimumHeight(28)
        for col in range(7):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        hh.setSectionsMovable(True)
        self.p12_table.verticalHeader().setVisible(False)
        self.p12_table.verticalHeader().setDefaultSectionSize(28)
        self.p12_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p12_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.p12_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.p12_table.setAlternatingRowColors(True)
        self.p12_table.setSortingEnabled(True)
        self.p12_table.doubleClicked.connect(self._p12_on_double_click)
        layout.addWidget(self.p12_table, 1)

    def _p12_on_show(self) -> None:
        """Called when the Screener tab is shown."""
        pass

    def _p12_get_universe(self) -> list[str]:
        """Build the ticker universe from sector data and all portfolios."""
        tickers = set()
        for sector_tickers in SECTOR_DATA.values():
            tickers.update(sector_tickers)
        for pid in PORTFOLIO_IDS:
            entry = self._get_portfolio_entry(pid)
            for t in entry.get('portfolio', []):
                text = str(t or '').upper().strip()
                if text:
                    tickers.add(text)
        return sorted(tickers)

    def _p12_run_scan(self) -> None:
        """Launch a background scan with the current filters."""
        if self._p12_fetch_in_progress:
            return
        self._p12_fetch_in_progress = True
        self.p12_scan_btn.setEnabled(False)
        self.set_status_text(self.p12_status_lbl, 'Scanning...', status='info')

        mktcap_idx = self.p12_mktcap_combo.currentIndex()
        rsi_idx = self.p12_rsi_combo.currentIndex()
        trend_filter = _TREND_OPTIONS[self.p12_trend_combo.currentIndex()]
        tf_idx = self.p12_timeframe_combo.currentIndex()
        universe = self._p12_get_universe()

        threading.Thread(
            target=self._p12_fetch,
            args=(universe, mktcap_idx, rsi_idx, trend_filter, tf_idx),
            daemon=True,
        ).start()

    def _p12_fetch(self, universe: list[str], mktcap_idx: int, rsi_idx: int, trend_filter: str = 'Any', tf_idx: int = 1) -> None:
        """Fetch data and filter in background thread."""
        _, mktcap_min, mktcap_max = _MKTCAP_RANGES[mktcap_idx]
        _, rsi_min, rsi_max = _RSI_RANGES[rsi_idx]
        _, tf_period, tf_interval = _TIMEFRAME_OPTIONS[tf_idx]

        results: list[ScreenerResult] = []

        try:
            # Batch download price history
            batch = yf.download(
                universe, period=tf_period, interval=tf_interval,
                group_by='ticker', progress=False, auto_adjust=False, threads=False,
            )
            is_multi = isinstance(batch.columns, pd.MultiIndex)

            def _get_close_series(ticker: str) -> Any:
                try:
                    if is_multi and ticker in batch.columns.get_level_values(0):
                        return batch[ticker]['Close'].dropna()
                    elif not is_multi and 'Close' in batch.columns and len(universe) == 1:
                        return batch['Close'].dropna()
                except Exception:
                    pass
                return pd.Series(dtype=float)

            # Fetch market caps sequentially to avoid crumb invalidation
            mkt_caps: dict[str, float | None] = {}
            for ticker in universe:
                try:
                    with YF_LOCK:
                        t_obj = yf.Ticker(ticker)
                        fast_info = getattr(t_obj, 'fast_info', {}) or {}
                    mc = fast_info.get('marketCap')
                    if mc:
                        mkt_caps[ticker] = float(mc)
                        continue
                    with YF_LOCK:
                        info = yf.Ticker(ticker).info
                    mc = info.get('marketCap')
                    mkt_caps[ticker] = float(mc) if mc else None
                except Exception:
                    mkt_caps[ticker] = None

            for ticker in universe:
                close = _get_close_series(ticker)
                mc = mkt_caps.get(ticker)

                # Market cap filter
                if mktcap_min is not None and (mc is None or mc < mktcap_min):
                    continue
                if mktcap_max is not None and (mc is None or mc >= mktcap_max):
                    continue

                # RSI
                rsi = _compute_rsi(close)

                # RSI filter
                if rsi_min is not None and (rsi is None or rsi < rsi_min):
                    continue
                if rsi_max is not None and (rsi is None or rsi >= rsi_max):
                    continue

                # Linear regression trend
                trend, trend_slope = _compute_linreg_trend(close)

                # Trend filter
                if trend_filter != 'Any':
                    if trend is None or trend != trend_filter:
                        continue

                # Price and change
                price = None
                change = None
                if len(close) >= 2:
                    price = float(close.iloc[-1])
                    prev = float(close.iloc[-2])
                    change = (price - prev) / prev * 100 if prev else 0.0
                elif len(close) == 1:
                    price = float(close.iloc[-1])
                    change = 0.0

                results.append(ScreenerResult(
                    ticker=ticker, price=price, change=change,
                    mkt_cap=mc, rsi=rsi, trend=trend,
                    trend_slope=trend_slope,
                ))

            self._invoke_main.emit(lambda r=results: self._p12_complete_scan(r))
        except Exception as e:
            logger.error(f'Screener scan failed: {e}')
            self._invoke_main.emit(self._p12_fail_scan)

    def _p12_complete_scan(self, results: list[ScreenerResult]) -> None:
        """Apply scan results to the table."""
        self._p12_fetch_in_progress = False
        self.p12_scan_btn.setEnabled(True)
        self._p12_results = results
        self.set_status_text(self.p12_status_lbl, f'{len(results)} results', status='positive')
        self._p12_populate_table(results)

    def _p12_fail_scan(self) -> None:
        """Handle a failed scan."""
        self._p12_fetch_in_progress = False
        self.p12_scan_btn.setEnabled(True)
        self.set_status_text(self.p12_status_lbl, 'Scan failed', status='negative')

    def _p12_populate_table(self, results: list[ScreenerResult]) -> None:
        """Fill the results table."""
        self.p12_table.setSortingEnabled(False)
        self.p12_table.setRowCount(len(results))

        for row, r in enumerate(results):
            # Ticker
            ticker_item = QTableWidgetItem(r.ticker)
            ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ticker_item.setForeground(self.theme_qcolor('text_primary'))
            font = ticker_item.font()
            font.setBold(True)
            ticker_item.setFont(font)
            self.p12_table.setItem(row, 0, ticker_item)

            # Price
            price_text = f'${r.price:.2f}' if isinstance(r.price, (int, float)) else '--'
            price_item = QTableWidgetItem(price_text)
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if isinstance(r.price, (int, float)):
                price_item.setData(Qt.ItemDataRole.UserRole, float(r.price))
            self.p12_table.setItem(row, 1, price_item)

            # Change %
            if isinstance(r.change, (int, float)):
                sign = '+' if r.change >= 0 else ''
                change_item = QTableWidgetItem(f'{sign}{r.change:.2f}%')
                change_item.setForeground(QColor(CLR_UP) if r.change >= 0 else QColor(CLR_DOWN))
                change_item.setData(Qt.ItemDataRole.UserRole, float(r.change))
            else:
                change_item = QTableWidgetItem('--')
                change_item.setForeground(QColor('#555'))
            change_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p12_table.setItem(row, 2, change_item)

            # Market Cap
            if isinstance(r.mkt_cap, (int, float)) and r.mkt_cap > 0:
                cap_text = fmt_num(r.mkt_cap)
                cap_item = QTableWidgetItem(cap_text)
                cap_item.setForeground(QColor(self._mktcap_color(r.mkt_cap)))
                cap_item.setData(Qt.ItemDataRole.UserRole, float(r.mkt_cap))
            else:
                cap_item = QTableWidgetItem('--')
                cap_item.setForeground(QColor('#555'))
            cap_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p12_table.setItem(row, 3, cap_item)

            # RSI
            if isinstance(r.rsi, (int, float)):
                rsi_text = f'{r.rsi:.1f}'
                rsi_item = QTableWidgetItem(rsi_text)
                if r.rsi >= 70:
                    rsi_item.setForeground(QColor(CLR_DOWN))
                elif r.rsi <= 30:
                    rsi_item.setForeground(QColor(CLR_UP))
                else:
                    rsi_item.setForeground(self.theme_qcolor('text_primary'))
                rsi_item.setData(Qt.ItemDataRole.UserRole, float(r.rsi))
            else:
                rsi_item = QTableWidgetItem('--')
                rsi_item.setForeground(QColor('#555'))
            rsi_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p12_table.setItem(row, 4, rsi_item)

            # Trend
            if r.trend:
                trend_item = QTableWidgetItem(r.trend)
                if r.trend == 'Upward':
                    trend_item.setForeground(QColor(CLR_UP))
                elif r.trend == 'Downward':
                    trend_item.setForeground(QColor(CLR_DOWN))
                else:
                    trend_item.setForeground(self.theme_qcolor('text_muted'))
            else:
                trend_item = QTableWidgetItem('--')
                trend_item.setForeground(QColor('#555'))
            trend_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p12_table.setItem(row, 5, trend_item)

            # Slope %/day
            if isinstance(r.trend_slope, (int, float)):
                sign = '+' if r.trend_slope >= 0 else ''
                slope_item = QTableWidgetItem(f'{sign}{r.trend_slope:.3f}')
                if r.trend_slope > 0:
                    slope_item.setForeground(QColor(CLR_UP))
                elif r.trend_slope < 0:
                    slope_item.setForeground(QColor(CLR_DOWN))
                else:
                    slope_item.setForeground(self.theme_qcolor('text_muted'))
                slope_item.setData(Qt.ItemDataRole.UserRole, float(r.trend_slope))
            else:
                slope_item = QTableWidgetItem('--')
                slope_item.setForeground(QColor('#555'))
            slope_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.p12_table.setItem(row, 6, slope_item)

        self.p12_table.setSortingEnabled(True)

    def _p12_on_double_click(self, index: Any) -> None:
        """Double-click a row to jump to Charts with that ticker."""
        row = index.row()
        item = self.p12_table.item(row, 0)
        if not item:
            return
        symbol = item.text().strip()
        if not symbol:
            return
        if hasattr(self, 'p10_symbol_input'):
            self.p10_symbol_input.setText(symbol)
        if hasattr(self, 'p10_symbol'):
            self.p10_symbol = symbol
        self.switch_page(6)
        if hasattr(self, '_p10_load_from_input'):
            self._p10_load_from_input()
