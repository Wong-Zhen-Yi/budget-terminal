from __future__ import annotations
import math
from typing import Any
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QBrush, QFont, QPen
from ..compat import *
from budget_terminal_app.workers.pre_market import PreMarketWorker


def _fg_score_color(score: float | None) -> str:
    if score is None:
        return '#888888'
    if score < 25:
        return '#ea2962'
    if score < 45:
        return '#f0824a'
    if score < 55:
        return '#f5c543'
    if score < 75:
        return '#56b568'
    return '#16a34a'


class _FearGreedGauge(QWidget):
    """Semicircular gauge mimicking the CNN Fear & Greed dial."""

    _ZONES = [
        (0, 25, '#ea2962'),
        (25, 45, '#f0824a'),
        (45, 55, '#f5c543'),
        (55, 75, '#56b568'),
        (75, 100, '#16a34a'),
    ]
    _LABELS = [
        (12.5, 'EXTREME\nFEAR'),
        (35, 'FEAR'),
        (50, 'NEUTRAL'),
        (65, 'GREED'),
        (87.5, 'EXTREME\nGREED'),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._score: float | None = None
        self._text_color = '#1a1a1a'
        self._muted_color = '#666666'
        self.setMinimumSize(320, 220)

    def set_data(self, score: float | None) -> None:
        self._score = score
        self.update()

    def set_colors(self, text: str, muted: str) -> None:
        self._text_color = text
        self._muted_color = muted

    def paintEvent(self, event: Any) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        score_h = 38
        top_margin = 22          # room for "NEUTRAL" label above the arc
        cx = w // 2
        cy = h - score_h
        radius = min(cx - 30, cy - top_margin)
        if radius < 40:
            p.end()
            return

        aw = max(18, radius // 4)  # arc stroke width
        ar = radius - aw // 2      # arc center-line radius
        arc_rect = QRectF(cx - ar, cy - ar, 2 * ar, 2 * ar)

        # Filled wedge for the active zone
        if self._score is not None:
            for s0, s1, clr in self._ZONES:
                if s0 <= self._score <= s1 or (s1 == 100 and self._score >= s0):
                    fill_c = QColor(clr)
                    fill_c.setAlpha(50)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(fill_c))
                    ir = ar - aw // 2
                    p.drawPie(QRectF(cx - ir, cy - ir, 2 * ir, 2 * ir),
                              int((180 - s1 * 1.8) * 16),
                              int((s1 - s0) * 1.8 * 16))
                    break

        # Zone arcs
        for s0, s1, clr in self._ZONES:
            pen = QPen(QColor(clr), aw)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawArc(arc_rect,
                       int((180 - s1 * 1.8) * 16),
                       int((s1 - s0) * 1.8 * 16))

        # Tick dots at zone boundaries
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._muted_color)))
        for val in [25, 50, 75]:
            a = math.radians(180 - val * 1.8)
            p.drawEllipse(QPointF(cx + ar * math.cos(a), cy - ar * math.sin(a)), 2.5, 2.5)

        # Tick numbers — placed outside the arc
        font = QFont()
        font.setPixelSize(11)
        p.setFont(font)
        p.setPen(QColor(self._muted_color))
        tr = ar + aw // 2 + 14
        for val in [0, 25, 50, 75, 100]:
            a = math.radians(180 - val * 1.8)
            tx = cx + tr * math.cos(a)
            ty = cy - tr * math.sin(a)
            p.drawText(QRectF(tx - 18, ty - 9, 36, 18), Qt.AlignmentFlag.AlignCenter, str(val))

        # Zone labels — placed outside the arc, further out than tick numbers
        font.setPixelSize(9)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(self._muted_color))
        label_r = ar + aw // 2 + 30
        for mid, text in self._LABELS:
            a_deg = 180 - mid * 1.8
            a_rad = math.radians(a_deg)
            lx = cx + label_r * math.cos(a_rad)
            ly = cy - label_r * math.sin(a_rad)
            p.save()
            p.translate(lx, ly)
            # Rotate so text follows the arc tangent
            p.rotate(-a_deg + 90)
            p.drawText(QRectF(-32, -16, 64, 32), Qt.AlignmentFlag.AlignCenter, text)
            p.restore()

        # Needle
        if self._score is not None:
            a_rad = math.radians(180 - self._score * 1.8)
            nr = ar - aw // 2 - 2
            nx = cx + nr * math.cos(a_rad)
            ny = cy - nr * math.sin(a_rad)
            p.setPen(QPen(QColor(self._text_color), 3))
            p.setBrush(QBrush(QColor(self._text_color)))
            p.drawLine(QPointF(cx, cy), QPointF(nx, ny))
            p.drawEllipse(QPointF(cx, cy), 5, 5)

            # Score number
            font.setPixelSize(24)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(self._text_color))
            p.drawText(QRectF(cx - 35, cy + 8, 70, score_h),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                        str(int(self._score)))

        p.end()


class PreMarketMixin:

    def init_page14(self) -> None:
        """Build the Pre-Market page UI."""
        self._p14_thread: QThread | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_lbl = QLabel('<b>Pre-Market</b>')
        self.set_theme_role(title_lbl, 'page_title')
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        self.p14_refresh_btn = QPushButton('Refresh')
        self.set_theme_variant(self.p14_refresh_btn, 'accent')
        self.p14_refresh_btn.clicked.connect(self._p14_refresh)
        title_row.addWidget(self.p14_refresh_btn)
        layout.addLayout(title_row)

        self.p14_status_lbl = QLabel('Ready')
        self.set_theme_role(self.p14_status_lbl, 'status_muted')
        layout.addWidget(self.p14_status_lbl)

        # --- Macro overview row ---
        macro_panel_max_height = 175
        macro_row = QHBoxLayout()
        macro_row.setSpacing(4)

        # Top-left: Futures
        futures_frame = self._p14_make_panel()
        futures_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        futures_frame.setMaximumHeight(macro_panel_max_height)
        futures_lay = QVBoxLayout(futures_frame)
        futures_lay.setContentsMargins(4, 1, 4, 1)
        futures_lay.setSpacing(0)
        futures_title = QLabel('<b>Futures</b>')
        self.set_theme_role(futures_title, 'section_title')
        futures_title.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        futures_lay.addWidget(futures_title)
        self.p14_futures_table = QTableWidget(len(PreMarketWorker._FUTURES_CONTRACTS), 5)
        self.p14_futures_table.setHorizontalHeaderLabels(['Ticker', 'Name', 'Price', 'Chg %', 'Direction'])
        futures_header = self.p14_futures_table.horizontalHeader()
        futures_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        futures_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        futures_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        futures_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        futures_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        futures_header.setStretchLastSection(False)
        futures_header.setMinimumHeight(20)
        futures_header.setDefaultSectionSize(20)
        self.p14_futures_table.verticalHeader().setVisible(False)
        self.p14_futures_table.verticalHeader().setDefaultSectionSize(18)
        self.p14_futures_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p14_futures_table.setAlternatingRowColors(True)
        self.p14_futures_table.setWordWrap(False)
        self.p14_futures_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.p14_futures_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        futures_lay.addWidget(self.p14_futures_table, 1)
        macro_row.addWidget(futures_frame, 1)

        # Top-right: DXY
        dxy_frame = self._p14_make_panel()
        dxy_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        dxy_frame.setMaximumHeight(macro_panel_max_height)
        dxy_lay = QVBoxLayout(dxy_frame)
        dxy_lay.setContentsMargins(6, 2, 6, 2)
        dxy_lay.setSpacing(0)
        dxy_title = QLabel('<b>DXY</b>')
        self.set_theme_role(dxy_title, 'section_title')
        dxy_title.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        dxy_lay.addWidget(dxy_title)
        self.p14_dxy_level = QLabel('Level: --')
        self.p14_dxy_chg = QLabel('1d Change: --')
        self.p14_dxy_trend = QLabel('5d Trend: --')
        self.p14_dxy_note = QLabel('')
        self.set_theme_role(self.p14_dxy_note, 'status_muted')
        self.p14_dxy_note.setWordWrap(True)
        for lbl in [self.p14_dxy_level, self.p14_dxy_chg, self.p14_dxy_trend]:
            lbl.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
            dxy_lay.addWidget(lbl)
        dxy_lay.addWidget(self.p14_dxy_note)
        macro_row.addWidget(dxy_frame, 1)

        # Bottom-left: TNX
        tnx_frame = self._p14_make_panel()
        tnx_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tnx_frame.setMaximumHeight(macro_panel_max_height)
        tnx_lay = QVBoxLayout(tnx_frame)
        tnx_lay.setContentsMargins(4, 1, 4, 1)
        tnx_lay.setSpacing(0)
        tnx_title = QLabel('<b>10Y Yield</b>')
        self.set_theme_role(tnx_title, 'section_title')
        tnx_title.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        tnx_lay.addWidget(tnx_title)
        tnx_row = QHBoxLayout()
        tnx_row.setSpacing(8)
        self.p14_tnx_yield = QLabel('Yield: --')
        self.p14_tnx_chg = QLabel('1d Change: --')
        self.p14_tnx_vs_avg = QLabel('vs 20d Avg: --')
        for lbl in [self.p14_tnx_yield, self.p14_tnx_chg, self.p14_tnx_vs_avg]:
            lbl.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
            tnx_row.addWidget(lbl)
        tnx_row.addStretch()
        tnx_lay.addLayout(tnx_row)
        self.p14_tnx_warn = QLabel('')
        self.set_theme_role(self.p14_tnx_warn, 'status_muted')
        self.p14_tnx_warn.setWordWrap(True)
        tnx_lay.addWidget(self.p14_tnx_warn)
        macro_row.addWidget(tnx_frame, 1)

        # Bottom-right: VIX
        vix_frame = self._p14_make_panel()
        vix_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        vix_frame.setMaximumHeight(macro_panel_max_height)
        vix_lay = QVBoxLayout(vix_frame)
        vix_lay.setContentsMargins(6, 2, 6, 2)
        vix_lay.setSpacing(0)
        vix_title = QLabel('<b>VIX</b>')
        self.set_theme_role(vix_title, 'section_title')
        vix_title.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
        vix_lay.addWidget(vix_title)
        self.p14_vix_level = QLabel('Level: --')
        self.p14_vix_chg = QLabel('1d Change: --')
        self.p14_vix_regime = QLabel('Regime: --')
        for lbl in [self.p14_vix_level, self.p14_vix_chg, self.p14_vix_regime]:
            lbl.setStyleSheet(f'color: {self.theme_color("text_primary")}; border: none;')
            vix_lay.addWidget(lbl)
        macro_row.addWidget(vix_frame, 1)

        layout.addLayout(macro_row)

        # --- Fear & Greed + Market Momentum (side by side) ---
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        # Left: Fear & Greed Index
        fg_col = QVBoxLayout()
        fg_col.setSpacing(4)
        fg_col.addWidget(self._p14_section_label('Fear & Greed Index'))
        fg_outer = self._p14_make_panel()
        fg_outer.setStyleSheet(
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: none; border-radius: 6px; }}'
        )
        fg_lay = QHBoxLayout(fg_outer)
        fg_lay.setContentsMargins(12, 10, 12, 10)
        fg_lay.setSpacing(16)

        self.p14_fg_gauge = _FearGreedGauge()
        self.p14_fg_gauge.set_colors(
            self.theme_color('text_primary'),
            self.theme_color('text_secondary') if hasattr(self, 'theme_color') else '#888',
        )
        fg_lay.addWidget(self.p14_fg_gauge, 3)

        hist_col = QVBoxLayout()
        hist_col.setSpacing(6)
        self._p14_fg_hist_widgets: list[QWidget] = []
        self.p14_fg_history_box = QVBoxLayout()
        self.p14_fg_history_box.setSpacing(4)
        for period in ['Previous close', '1 week ago', '1 month ago', '1 year ago']:
            row = self._p14_fg_history_row(period, '--', None)
            self.p14_fg_history_box.addWidget(row)
            self._p14_fg_hist_widgets.append(row)
        hist_col.addLayout(self.p14_fg_history_box)
        hist_col.addStretch()
        self.p14_fg_updated_lbl = QLabel('')
        self.set_theme_role(self.p14_fg_updated_lbl, 'status_muted')
        hist_col.addWidget(self.p14_fg_updated_lbl)
        fg_lay.addLayout(hist_col, 2)

        fg_col.addWidget(fg_outer)
        bottom_row.addLayout(fg_col, 1)

        # Right: Market Momentum
        mom_col = QVBoxLayout()
        mom_col.setSpacing(4)
        mom_col.addWidget(self._p14_section_label('Market Momentum'))
        momentum_frame = self._p14_make_panel()
        momentum_lay = QVBoxLayout(momentum_frame)
        momentum_lay.setContentsMargins(8, 6, 8, 6)
        momentum_lay.setSpacing(4)

        self.p14_momentum_axis = DateAxisItem(orientation='bottom')
        self.p14_momentum_plot = pg.PlotWidget(axisItems={'bottom': self.p14_momentum_axis})
        self.p14_momentum_plot.showGrid(x=True, y=True, alpha=0.12)
        self.p14_momentum_plot.getPlotItem().hideAxis('left')
        self.p14_momentum_plot.getPlotItem().showAxis('right')
        self.p14_momentum_plot.getPlotItem().setMenuEnabled(False)
        self.p14_momentum_plot.setMouseEnabled(x=False, y=False)
        self.p14_momentum_plot.getPlotItem().vb.setMouseMode(pg.ViewBox.RectMode)
        self.p14_momentum_plot.getPlotItem().vb.setMouseEnabled(x=False, y=False)
        self.p14_momentum_plot.setMinimumHeight(220)
        bg = self.theme_color('panel_background')
        self.p14_momentum_plot.setBackground(bg)
        momentum_lay.addWidget(self.p14_momentum_plot)

        self.p14_momentum_lbl = QLabel('SPY: -- | 125-day MA: -- | --')
        self.p14_momentum_lbl.setStyleSheet(
            f'color: {self.theme_color("text_primary")}; border: none; font-size: 12px;'
        )
        momentum_lay.addWidget(self.p14_momentum_lbl)
        mom_col.addWidget(momentum_frame)
        bottom_row.addLayout(mom_col, 1)

        layout.addLayout(bottom_row)

        layout.addStretch()
        scroll.setWidget(container)
        page_layout = QVBoxLayout(self.page14)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)

    # ---- helpers ----

    def _p14_section_label(self, text: str) -> QLabel:
        lbl = QLabel(f'<b>{text}</b>')
        self.set_theme_role(lbl, 'section_title')
        return lbl

    def _p14_make_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f'QFrame {{ background: {self.theme_color("panel_background")}; '
            f'border: 1px solid {self.theme_color("panel_border")}; border-radius: 6px; }}'
        )
        return frame

    def _p14_wrap_panel(self, widget: Any) -> QFrame:
        frame = self._p14_make_panel()
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(widget)
        return frame

    def _p14_fg_history_row(self, period: str, rating: str, score: float | None) -> QWidget:
        row = QWidget()
        row.setStyleSheet('background: transparent; border: none;')
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 2, 0, 2)
        row_lay.setSpacing(8)
        left_widget = QWidget()
        left_widget.setStyleSheet('background: transparent; border: none;')
        left_widget.setFixedWidth(100)
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        period_lbl = QLabel(period)
        period_lbl.setStyleSheet(
            f'color: {self.theme_color("text_secondary") if hasattr(self, "theme_color") else "#888"}; '
            f'font-size: 10px; border: none;'
        )
        rating_lbl = QLabel(f'<b>{rating}</b>')
        rating_lbl.setStyleSheet(
            f'color: {self.theme_color("text_primary")}; border: none;'
        )
        left.addWidget(period_lbl)
        left.addWidget(rating_lbl)
        row_lay.addWidget(left_widget)
        clr = _fg_score_color(score)
        badge_text = str(int(score)) if score is not None else '--'
        badge = QLabel(badge_text)
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f'background: transparent; color: {clr}; '
            f'border: 2px solid {clr}; border-radius: 17px; '
            f'font-weight: bold; font-size: 12px;'
        )
        row_lay.addWidget(badge)
        row_lay.addStretch()
        return row

    # ---- worker lifecycle ----

    def _p14_refresh(self) -> None:
        if self._p14_thread is not None and self._p14_thread.isRunning():
            return
        self.p14_refresh_btn.setEnabled(False)
        self.set_status_text(self.p14_status_lbl, 'Fetching pre-market data...', status='muted')
        watchlist = list(getattr(self, 'tickers', []))
        worker = PreMarketWorker(watchlist)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._p14_on_data)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._p14_on_error)
        worker.error.connect(thread.quit)
        self._p14_thread = thread
        self._p14_worker = worker
        thread.start()

    def _p14_on_data(self, result: dict) -> None:
        self.p14_refresh_btn.setEnabled(True)

        # Futures
        futures = result.get('futures', [])
        self.p14_futures_table.setRowCount(len(futures))
        for r, row in enumerate(futures):
            self.p14_futures_table.setItem(r, 0, QTableWidgetItem(row['ticker']))
            self.p14_futures_table.setItem(r, 1, QTableWidgetItem(row.get('name', '')))
            self.p14_futures_table.setItem(r, 2, QTableWidgetItem(f"{row['price']:.2f}"))
            chg_item = QTableWidgetItem(f"{row['change_pct']:+.2f}%")
            chg_item.setForeground(QColor('#00c853') if row['change_pct'] >= 0 else QColor('#ff1744'))
            self.p14_futures_table.setItem(r, 3, chg_item)
            self.p14_futures_table.setItem(r, 4, QTableWidgetItem(row['direction']))
        if futures:
            self.p14_futures_table.resizeColumnToContents(0)
            self.p14_futures_table.resizeColumnToContents(2)
            self.p14_futures_table.resizeColumnToContents(3)
            self.p14_futures_table.resizeColumnToContents(4)

        # DXY
        dxy = result.get('dxy', {})
        if dxy:
            self.p14_dxy_level.setText(f"Level: {dxy['level']:.2f}")
            self.p14_dxy_chg.setText(f"1d Change: {dxy['change_1d']:+.2f}%")
            self.p14_dxy_trend.setText(f"5d Trend: {dxy['trend']}")
            if dxy['trend'] == 'Strengthening':
                self.p14_dxy_note.setText('Rising dollar — headwind for equities & commodities')
            elif dxy['trend'] == 'Weakening':
                self.p14_dxy_note.setText('Falling dollar — tailwind for equities & commodities')
            else:
                self.p14_dxy_note.setText('')

        # TNX
        tnx = result.get('tnx', {})
        if tnx:
            self.p14_tnx_yield.setText(f"Yield: {tnx['yield']:.3f}%")
            self.p14_tnx_chg.setText(f"1d Change: {tnx['change_bps']:+.1f} bps")
            self.p14_tnx_vs_avg.setText(f"vs 20d Avg: {tnx['vs_avg']:+.3f}%")
            if tnx['change_bps'] > 5:
                self.p14_tnx_warn.setText('Yields rising sharply — watch rate-sensitive sectors')
            elif tnx['change_bps'] < -5:
                self.p14_tnx_warn.setText('Yields falling — bond rally, growth stocks may benefit')
            elif tnx['vs_avg'] > 0.1:
                self.p14_tnx_warn.setText('Yield remains above its 20-day average — financial conditions are still firm')
            elif tnx['vs_avg'] < -0.1:
                self.p14_tnx_warn.setText('Yield sits below its 20-day average — rates pressure is relatively lighter')
            else:
                self.p14_tnx_warn.setText('Yield is broadly stable versus the recent 20-day average')

        # VIX
        vix = result.get('vix', {})
        if vix:
            self.p14_vix_level.setText(f"Level: {vix['level']:.2f}")
            self.p14_vix_chg.setText(f"1d Change: {vix['change']:+.2f}")
            self.p14_vix_regime.setText(f"Regime: {vix['regime']}")

        # Fear & Greed — gauge + history
        fg = result.get('fear_greed', {})
        if fg:
            self.p14_fg_gauge.set_data(fg.get('score'))
            # Rebuild history rows
            for w in self._p14_fg_hist_widgets:
                w.setParent(None)
                w.deleteLater()
            self._p14_fg_hist_widgets.clear()
            for entry in fg.get('history', []):
                row = self._p14_fg_history_row(
                    entry['period'], entry.get('rating', '--'), entry.get('score'))
                self.p14_fg_history_box.addWidget(row)
                self._p14_fg_hist_widgets.append(row)
            ts = fg.get('timestamp', '')
            self.p14_fg_updated_lbl.setText(f'Last updated {ts}' if ts else '')

        # Market Momentum (SPY + 125-day MA)
        spy = result.get('spy_momentum', {})
        if spy and spy.get('dates'):
            self.p14_momentum_plot.clear()
            dates = spy['dates']
            closes = spy['closes']
            ma125 = spy['ma125']
            xs = list(range(len(dates)))
            self.p14_momentum_axis.set_dates(dates, '1d')
            # SPY close line
            self.p14_momentum_plot.plot(xs, closes, pen=pg.mkPen('#42a5f5', width=2), name='SPY')
            # 125-day MA — filter out NaN values
            ma_xs = [x for x, v in zip(xs, ma125) if v == v]  # NaN != NaN
            ma_ys = [v for v in ma125 if v == v]
            if ma_xs:
                self.p14_momentum_plot.plot(
                    ma_xs, ma_ys,
                    pen=pg.mkPen('#ffa726', width=2, style=Qt.PenStyle.DashLine),
                    name='125-day MA',
                )
            self.p14_momentum_plot.autoRange()
            # Summary label
            last_close = spy.get('last_close')
            last_ma = spy.get('last_ma')
            if last_close is not None and last_ma is not None:
                status = 'Above MA' if last_close >= last_ma else 'Below MA'
                clr = '#00c853' if last_close >= last_ma else '#ff1744'
                self.p14_momentum_lbl.setText(
                    f'SPY: ${last_close:.2f} | 125-day MA: ${last_ma:.2f} | '
                    f'<span style="color:{clr}">{status}</span>'
                )
            elif last_close is not None:
                self.p14_momentum_lbl.setText(f'SPY: ${last_close:.2f} | 125-day MA: -- | --')

        has_other_data = any(
            bool(result.get(key))
            for key in ('dxy', 'tnx', 'vix', 'fear_greed', 'spy_momentum')
        )
        if futures:
            self.set_status_text(self.p14_status_lbl, 'Data loaded', status='positive')
        elif has_other_data:
            self.set_status_text(
                self.p14_status_lbl,
                'Pre-market data loaded, but futures were unavailable.',
                status='warning',
            )
        else:
            self.set_status_text(self.p14_status_lbl, 'Pre-market data unavailable.', status='warning')

    def _p14_on_error(self, msg: str) -> None:
        self.p14_refresh_btn.setEnabled(True)
        self.set_status_text(self.p14_status_lbl, f'Error: {msg}', status='negative')
