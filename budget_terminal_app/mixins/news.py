from __future__ import annotations

import re
import time
from html import escape
from typing import Any

from PyQt6.QtCore import QStandardPaths

from ..compat import *
from budget_terminal_app.widgets.batched_render import DEFAULT_MAX_ITEMS, run_batched
from ..workers.data import DataWorker, NEWS_PAGE_REFRESH_REASON
from ..workers.news_preview import build_news_preview_text


NEWS_AI_PROMPT = (
    "You are a skeptical market-intelligence analyst. Treat this export as a lead set, not verified truth. "
    "Start with the user’s portfolio exposures, then search the broader market for the highest-alpha opportunities "
    "and risks, including bullish, bearish, relative-value, and watchlist ideas. Cross-reference every material "
    "claim against current independent sources and prioritize primary evidence such as company investor-relations "
    "releases and filings, regulators, government data, and original transcripts. Verify exact event and publication "
    "dates; separate confirmed facts from interpretation and forecasts; compare developments with prior expectations "
    "and what may already be priced in; assess the economic channel, likely magnitude, time horizon, catalysts, "
    "crowding, and portfolio read-throughs. Test at least one credible alternative explanation and seek disconfirming "
    "evidence. Rank ideas by potential impact, timing, evidence quality, confidence, and clear invalidation conditions. "
    "Cite the sources used, state unresolved evidence gaps, never treat syndicated repetition as independent "
    "confirmation, and do not invent missing facts. Existing signal scores and tags are heuristic discovery aids, "
    "not verified alpha. This is research assistance, not financial advice."
)


class _NewsPreviewSignals(QObject):
    preview_ready = pyqtSignal(int, object, object)


class _NewsCardHost(QWidget):
    width_changed = pyqtSignal(int)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.width_changed.emit(max(0, int(self.width())))


class _NewsArticleCard(QFrame):
    selected = pyqtSignal(object)
    activated = pyqtSignal(object)

    def __init__(self, article: dict[str, Any]) -> None:
        super().__init__()
        self.article = dict(article)
        self.setObjectName('newsArticleCard')
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(dict(self.article))
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(dict(self.article))
        super().mouseDoubleClickEvent(event)


class NewsMixin:

    def _p34_page_is_visible(self) -> bool:
        """Return whether News is the active real-app surface."""
        checker = getattr(self, '_is_current_page', None)
        if callable(checker):
            return bool(checker(getattr(self, 'page34', None)))
        return True

    def _p34_on_show(self) -> None:
        """Apply the newest shared Dashboard news payload once when visible."""
        dashboard_applied = False
        if hasattr(self, '_dashboard_apply_pending_page_data'):
            dashboard_applied = bool(self._dashboard_apply_pending_page_data('news'))
        if dashboard_applied:
            self._p34_render_pending = False
        elif getattr(self, '_p34_render_pending', False):
            self._p34_render_pending = False
            self._p34_refresh_cards()
        pending_preview = getattr(self, '_p34_pending_preview', None)
        if isinstance(pending_preview, tuple) and len(pending_preview) == 3:
            self._p34_pending_preview = None
            self._p34_on_preview_ready(*pending_preview)
        pending_status = getattr(self, '_p34_pending_status', None)
        if isinstance(pending_status, tuple) and len(pending_status) == 2:
            self._p34_pending_status = None
            self._p34_set_status(str(pending_status[0]), str(pending_status[1]))

    def _sort_articles_by_newest(self, articles: Any) -> Any:
        """Return newest articles first for shared news tables."""
        return sorted(articles, key=lambda article: article.get('_ts', 0), reverse=True)

    def _sort_articles_for_news_table(self, articles: Any) -> Any:
        """Return scored trader news by signal rank, otherwise newest first."""
        article_list = list(articles or [])
        if any(isinstance(article, dict) and '_trader_score' in article for article in article_list):
            return sorted(
                article_list,
                key=lambda article: (article.get('_trader_score', 0), article.get('_ts', 0)),
                reverse=True,
            )
        return self._sort_articles_by_newest(article_list)

    def _make_news_table(
        self,
        on_click: Any,
        on_double_click: Any | None = None,
        on_selection_change: Any | None = None,
        show_full_headlines: bool = False,
        time_header: str = 'Time',
        show_age: bool = False,
    ) -> Any:
        """Create a standard four-column news table for shared app surfaces."""
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(['Headline', 'Ticker', 'Source', time_header])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in range(1, 4):
            table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setWordWrap(True)
        if show_full_headlines:
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
            table.verticalHeader().setDefaultSectionSize(54)
            table.setProperty('bt_full_headlines', True)
        if show_age:
            table.setProperty('bt_show_age', True)
        table.itemClicked.connect(lambda item, tbl=table: on_click(item, tbl))
        if on_double_click is not None:
            table.itemDoubleClicked.connect(lambda item, tbl=table: on_double_click(item, tbl))
        if on_selection_change is not None:
            table.itemSelectionChanged.connect(lambda tbl=table: on_selection_change(tbl))
        return table

    def _news_table_article_age_text(self, article: Any) -> str:
        if not isinstance(article, dict):
            return '--'
        try:
            timestamp = float(article.get('_ts') or 0)
        except (TypeError, ValueError):
            return '--'
        if timestamp <= 0:
            return '--'
        age_seconds = max(0, int(time.time() - timestamp))
        if age_seconds < 60:
            return '<1m'
        if age_seconds < 3600:
            return f'{age_seconds // 60}m'
        if age_seconds < 86400:
            return f'{age_seconds // 3600}h'
        if age_seconds < 604800:
            return f'{age_seconds // 86400}d'
        if age_seconds < 31536000:
            return f'{age_seconds // 604800}w'
        return f'{age_seconds // 31536000}y'

    def _open_news_link_table(self, item: Any, table: Any) -> None:
        row = item.row()
        headline_item = table.item(row, 0)
        if headline_item:
            url = headline_item.data(Qt.ItemDataRole.UserRole)
            if url:
                logger.info('Opening news link: %s', url)
                webbrowser.open(url)

    def _populate_news_table(self, table: Any, articles: Any) -> None:
        """Populate a shared table without coupling it to the main News page."""
        table.setRowCount(0)
        for article in self._sort_articles_for_news_table(articles):
            row = table.rowCount()
            table.insertRow(row)
            headline = article.get('title', 'N/A')
            headline_item = QTableWidgetItem(headline)
            headline_item.setData(Qt.ItemDataRole.UserRole, article.get('url', ''))
            headline_item.setData(Qt.ItemDataRole.UserRole + 1, dict(article))
            headline_item.setToolTip(headline)
            table.setItem(row, 0, headline_item)
            ticker_item = QTableWidgetItem(article.get('ticker', ''))
            ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 1, ticker_item)
            source_item = QTableWidgetItem(article.get('source', ''))
            source_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 2, source_item)
            time_text = self._news_table_article_age_text(article) if table.property('bt_show_age') else article.get('time', '')
            time_item = QTableWidgetItem(time_text)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 3, time_item)
        if table.property('bt_full_headlines'):
            self._fit_full_headline_rows(table)
        table.clearSelection()
        table.setCurrentCell(-1, -1)
        table.scrollToTop()

    def _fit_full_headline_rows(self, table: Any) -> None:
        table.resizeRowsToContents()
        max_height_property = table.property('bt_full_headlines_max_height')
        max_height = 112 if max_height_property is None else int(max_height_property)
        for row in range(table.rowCount()):
            height = max(54, table.rowHeight(row))
            table.setRowHeight(row, min(max_height, height) if max_height > 0 else height)

    def init_page34(self) -> None:
        """Build the magazine-style News workspace."""
        self._p34_loaded_news = {'portfolio': [], 'macro': [], 'other': []}
        self._p34_highlighted_news: dict[str, Any] | None = None
        self._p34_visible_articles: list[dict[str, Any]] = []
        self._p34_preview_request_id = 0
        self._p34_news_refresh_request_id = 0
        self._p34_news_refresh_pending = False
        self._p34_news_refresh_signature: tuple[str, ...] = ()
        self._p34_news_refresh_queued_tickers: list[str] | None = None
        self._p34_ticker_search_request_id = 0
        self._p34_ticker_search_pending = False
        self._p34_ticker_search_tickers: list[str] = []
        self._p34_ticker_search_articles: list[dict[str, Any]] = []
        self._p34_ticker_search_empty_tickers: list[str] = []
        self._p34_ticker_search_failed_tickers: list[str] = []
        self._p34_active_filter = 'all'
        self._p34_card_columns = 0
        self._p34_render_generation = 0
        self._p34_render_pending = False
        self._p34_pending_preview: tuple[int, object, object] | None = None
        self._p34_pending_status: tuple[str, str] | None = None
        self._p34_ticker_search_cards: list[_NewsArticleCard] = []
        self._p34_portfolio_cards: list[_NewsArticleCard] = []
        self._p34_market_cards: list[_NewsArticleCard] = []
        self._p34_cards_by_key: dict[tuple[str, ...], _NewsArticleCard] = {}
        self._p34_preview_signals = _NewsPreviewSignals()
        self._p34_preview_signals.preview_ready.connect(self._p34_on_preview_ready)

        layout = QVBoxLayout(self.page34)
        layout.setContentsMargins(10, 10, 10, 4)
        layout.setSpacing(8)

        header = QFrame()
        self.set_theme_role(header, 'panel')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 9, 12, 9)
        header_layout.setSpacing(7)

        title = QLabel('News')
        self.set_theme_role(title, 'page_title')
        subtitle = QLabel('Portfolio-first news cards with a compact magazine reader.')
        self.set_theme_role(subtitle, 'muted')
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.p34_filter_buttons: dict[str, Any] = {}
        for key, label in (
            ('all', 'All'),
            ('portfolio', 'Portfolio'),
            ('market_macro', 'Market & Macro'),
        ):
            button = QPushButton(f'{label} (0)')
            button.setCheckable(True)
            button.setChecked(key == 'all')
            button.clicked.connect(lambda _checked=False, value=key: self._p34_set_filter(value))
            self.p34_filter_buttons[key] = button
            controls.addWidget(button)

        self.p34_search_input = QLineEdit()
        self.p34_search_input.setPlaceholderText('Filter headlines, tickers, sources, or signals')
        self.p34_search_input.setClearButtonEnabled(True)
        self.p34_search_input.textChanged.connect(self._p34_refresh_cards)
        controls.addWidget(self.p34_search_input, 1)

        self.p34_sort_combo = QComboBox()
        self.p34_sort_combo.addItems(['Newest', 'Signal'])
        self.p34_sort_combo.currentTextChanged.connect(self._p34_refresh_cards)
        controls.addWidget(self.p34_sort_combo)

        self.p34_export_btn = QPushButton('Export News for AI')
        self.set_theme_variant(self.p34_export_btn, 'positive')
        self.p34_export_btn.clicked.connect(self._p34_export_news_for_ai)
        controls.addWidget(self.p34_export_btn)
        header_layout.addLayout(controls)

        ticker_search_controls = QHBoxLayout()
        ticker_search_controls.setSpacing(6)
        ticker_search_label = QLabel('Outside-portfolio ticker news')
        self.set_theme_role(ticker_search_label, 'muted')
        ticker_search_controls.addWidget(ticker_search_label)
        self.p34_ticker_search_input = QLineEdit()
        self.p34_ticker_search_input.setPlaceholderText('Enter up to 10 tickers separated by commas, spaces, or new lines')
        self.p34_ticker_search_input.setClearButtonEnabled(True)
        self.p34_ticker_search_input.returnPressed.connect(self._p34_request_ticker_search)
        ticker_search_controls.addWidget(self.p34_ticker_search_input, 1)
        self.p34_ticker_search_btn = QPushButton('Search')
        self.set_theme_variant(self.p34_ticker_search_btn, 'accent')
        self.p34_ticker_search_btn.clicked.connect(self._p34_request_ticker_search)
        ticker_search_controls.addWidget(self.p34_ticker_search_btn)
        self.p34_ticker_search_clear_btn = QPushButton('Clear')
        self.p34_ticker_search_clear_btn.clicked.connect(self._p34_clear_ticker_search)
        ticker_search_controls.addWidget(self.p34_ticker_search_clear_btn)
        header_layout.addLayout(ticker_search_controls)

        self.p34_ticker_search_status_lbl = QLabel('Searches are temporary and do not change your portfolio.')
        self.p34_ticker_search_status_lbl.setWordWrap(True)
        self.set_theme_role(self.p34_ticker_search_status_lbl, 'status_muted')
        header_layout.addWidget(self.p34_ticker_search_status_lbl)

        self.p34_visible_count_lbl = QLabel('0 visible of 0 articles')
        self.set_theme_role(self.p34_visible_count_lbl, 'status_muted')
        header_layout.addWidget(self.p34_visible_count_lbl)
        layout.addWidget(header)

        self.p34_reader = QFrame()
        self.set_theme_role(self.p34_reader, 'panel')
        self.p34_reader.setMinimumHeight(190)
        self.p34_reader.setMaximumHeight(270)
        reader_layout = QHBoxLayout(self.p34_reader)
        reader_layout.setContentsMargins(12, 10, 12, 10)
        reader_layout.setSpacing(12)

        reader_info = QWidget()
        reader_info_layout = QVBoxLayout(reader_info)
        reader_info_layout.setContentsMargins(0, 0, 0, 0)
        reader_info_layout.setSpacing(6)
        selected_label = QLabel('SELECTED STORY')
        self.set_theme_role(selected_label, 'section_title')
        reader_info_layout.addWidget(selected_label)
        self.p34_reader_category_lbl = QLabel('No story selected')
        self.set_theme_role(self.p34_reader_category_lbl, 'accent')
        reader_info_layout.addWidget(self.p34_reader_category_lbl)
        self.p34_reader_title_lbl = QLabel('Select a news card to read it here')
        self.p34_reader_title_lbl.setWordWrap(True)
        self.p34_reader_title_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.set_theme_role(self.p34_reader_title_lbl, 'card_title')
        reader_info_layout.addWidget(self.p34_reader_title_lbl, 1)
        self.p34_reader_meta_lbl = QLabel('Ticker: -- | Source: -- | Age: --')
        self.p34_reader_meta_lbl.setWordWrap(True)
        self.set_theme_role(self.p34_reader_meta_lbl, 'muted')
        reader_info_layout.addWidget(self.p34_reader_meta_lbl)
        self.p34_reader_url_lbl = QLabel('URL: --')
        self.p34_reader_url_lbl.setWordWrap(True)
        self.p34_reader_url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.set_theme_role(self.p34_reader_url_lbl, 'muted')
        reader_info_layout.addWidget(self.p34_reader_url_lbl)
        self.p34_open_external_btn = QPushButton('Open Externally')
        self.p34_open_external_btn.setEnabled(False)
        self.set_theme_variant(self.p34_open_external_btn, 'positive')
        self.p34_open_external_btn.clicked.connect(self._p34_open_highlighted_news_external)
        reader_info_layout.addWidget(self.p34_open_external_btn)
        reader_layout.addWidget(reader_info, 5)

        self.p34_reader_body = QPlainTextEdit()
        self.p34_reader_body.setReadOnly(True)
        self.p34_reader_body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.p34_reader_body.setPlainText('Select a card to load a readable article preview.')
        reader_layout.addWidget(self.p34_reader_body, 7)
        layout.addWidget(self.p34_reader)

        self.p34_cards_scroll = QScrollArea()
        self.p34_cards_scroll.setWidgetResizable(True)
        self.p34_cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p34_cards_host = _NewsCardHost()
        self.p34_cards_host.setMinimumWidth(0)
        self.p34_cards_host.width_changed.connect(self._p34_reflow_cards)
        cards_layout = QVBoxLayout(self.p34_cards_host)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)

        self.p34_ticker_search_section = QWidget()
        ticker_search_section_layout = QVBoxLayout(self.p34_ticker_search_section)
        ticker_search_section_layout.setContentsMargins(0, 0, 0, 0)
        ticker_search_section_layout.setSpacing(6)
        ticker_search_title = QLabel('Ticker Search')
        self.set_theme_role(ticker_search_title, 'section_title')
        ticker_search_section_layout.addWidget(ticker_search_title)
        self.p34_ticker_search_meta_lbl = QLabel('')
        self.p34_ticker_search_meta_lbl.setWordWrap(True)
        self.set_theme_role(self.p34_ticker_search_meta_lbl, 'muted')
        ticker_search_section_layout.addWidget(self.p34_ticker_search_meta_lbl)
        self.p34_ticker_search_grid_host = QWidget()
        self.p34_ticker_search_grid = QGridLayout(self.p34_ticker_search_grid_host)
        self.p34_ticker_search_grid.setContentsMargins(0, 0, 0, 0)
        self.p34_ticker_search_grid.setHorizontalSpacing(8)
        self.p34_ticker_search_grid.setVerticalSpacing(8)
        ticker_search_section_layout.addWidget(self.p34_ticker_search_grid_host)
        self.p34_ticker_search_section.setVisible(False)
        cards_layout.addWidget(self.p34_ticker_search_section)

        self.p34_portfolio_section = QWidget()
        portfolio_section_layout = QVBoxLayout(self.p34_portfolio_section)
        portfolio_section_layout.setContentsMargins(0, 0, 0, 0)
        portfolio_section_layout.setSpacing(6)
        portfolio_title = QLabel('Portfolio Spotlight')
        self.set_theme_role(portfolio_title, 'section_title')
        portfolio_section_layout.addWidget(portfolio_title)
        self.p34_portfolio_grid_host = QWidget()
        self.p34_portfolio_grid = QGridLayout(self.p34_portfolio_grid_host)
        self.p34_portfolio_grid.setContentsMargins(0, 0, 0, 0)
        self.p34_portfolio_grid.setHorizontalSpacing(8)
        self.p34_portfolio_grid.setVerticalSpacing(8)
        portfolio_section_layout.addWidget(self.p34_portfolio_grid_host)
        cards_layout.addWidget(self.p34_portfolio_section)

        self.p34_market_section = QWidget()
        market_section_layout = QVBoxLayout(self.p34_market_section)
        market_section_layout.setContentsMargins(0, 0, 0, 0)
        market_section_layout.setSpacing(6)
        market_title = QLabel('Market & Macro')
        self.set_theme_role(market_title, 'section_title')
        market_section_layout.addWidget(market_title)
        self.p34_market_grid_host = QWidget()
        self.p34_market_grid = QGridLayout(self.p34_market_grid_host)
        self.p34_market_grid.setContentsMargins(0, 0, 0, 0)
        self.p34_market_grid.setHorizontalSpacing(8)
        self.p34_market_grid.setVerticalSpacing(8)
        market_section_layout.addWidget(self.p34_market_grid_host)
        cards_layout.addWidget(self.p34_market_section)
        cards_layout.addStretch()

        self.p34_cards_scroll.setWidget(self.p34_cards_host)
        layout.addWidget(self.p34_cards_scroll, 1)
        self._apply_news_theme()

    def _apply_news_theme(self) -> None:
        """Refresh theme-dependent News controls and cards."""
        active = getattr(self, '_p34_active_filter', 'all')
        for key, button in getattr(self, 'p34_filter_buttons', {}).items():
            button.setChecked(key == active)
            self.set_theme_variant(button, 'accent' if key == active else None)
        for card in list(getattr(self, '_p34_cards_by_key', {}).values()):
            self._p34_style_card(card)
        self._p34_style_reader_category()

    def _p34_set_status(self, text: str, status: str) -> None:
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=status)

    def _p34_publish_status(self, text: str, status: str) -> None:
        """Avoid replacing the destination page's status from a hidden completion."""
        if self._p34_page_is_visible():
            self._p34_pending_status = None
            self._p34_set_status(text, status)
        else:
            self._p34_pending_status = (str(text), str(status))

    def _p34_numeric(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _p34_article_age_text(self, article: Any) -> str:
        if not isinstance(article, dict):
            return '--'
        timestamp = self._p34_numeric(article.get('_ts'))
        if timestamp <= 0:
            return '--'
        age_seconds = max(0, int(time.time() - timestamp))
        if age_seconds < 60:
            return '<1m'
        if age_seconds < 3600:
            return f'{age_seconds // 60}m'
        if age_seconds < 86400:
            return f'{age_seconds // 3600}h'
        if age_seconds < 604800:
            return f'{age_seconds // 86400}d'
        if age_seconds < 31536000:
            return f'{age_seconds // 604800}w'
        return f'{age_seconds // 31536000}y'

    def _p34_article_key(self, article: Any) -> tuple[str, ...]:
        if not isinstance(article, dict):
            return ('',)
        url = str(article.get('url') or '').strip()
        if url:
            return ('url', url)
        return (
            'fallback',
            str(article.get('title') or '').strip(),
            str(article.get('source') or '').strip(),
            str(article.get('time') or '').strip(),
        )

    def _p34_category_label(self, article: Any) -> str:
        category = str(article.get('category') or '') if isinstance(article, dict) else ''
        return {
            'portfolio': 'Portfolio',
            'macro': 'Macro',
            'other': 'Market',
            'search': 'Ticker Search',
        }.get(category, 'Market')

    def _p34_category_token(self, article: Any) -> str:
        return {
            'Portfolio': 'accent_positive',
            'Macro': 'warning',
            'Market': 'info',
            'Ticker Search': 'accent',
        }.get(self._p34_category_label(article), 'text_secondary')

    def _p34_signal_text(self, article: Any) -> str:
        tags = article.get('_signal_tags', []) if isinstance(article, dict) else []
        if not isinstance(tags, (list, tuple)):
            return ''
        return ' · '.join(str(tag).title() for tag in tags if str(tag).strip())

    def _p34_all_articles(self) -> list[dict[str, Any]]:
        loaded = getattr(self, '_p34_loaded_news', {})
        return [
            dict(article)
            for category in ('portfolio', 'macro', 'other')
            for article in loaded.get(category, [])
            if isinstance(article, dict)
        ]

    def _p34_set_filter(self, filter_key: str) -> None:
        self._p34_active_filter = filter_key if filter_key in {'all', 'portfolio', 'market_macro'} else 'all'
        self._apply_news_theme()
        self._p34_refresh_cards()

    def _p34_article_matches_text_filter(self, article: dict[str, Any], query: str) -> bool:
        if not query:
            return True
        haystack = ' '.join(
            (
                str(article.get('title') or ''),
                str(article.get('ticker') or ''),
                str(article.get('source') or ''),
                self._p34_category_label(article),
                self._p34_signal_text(article),
            )
        ).casefold()
        return query in haystack

    def _p34_filtered_ticker_search_articles(self) -> list[dict[str, Any]]:
        query = self.p34_search_input.text().strip().casefold() if hasattr(self, 'p34_search_input') else ''
        articles = [
            dict(article)
            for article in getattr(self, '_p34_ticker_search_articles', [])
            if isinstance(article, dict) and self._p34_article_matches_text_filter(article, query)
        ]
        return sorted(articles, key=lambda item: self._p34_numeric(item.get('_ts')), reverse=True)

    def _p34_filtered_groups(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        query = self.p34_search_input.text().strip().casefold() if hasattr(self, 'p34_search_input') else ''
        active_filter = getattr(self, '_p34_active_filter', 'all')
        portfolio = []
        market = []
        for article in self._p34_all_articles():
            category = str(article.get('category') or '')
            if active_filter == 'portfolio' and category != 'portfolio':
                continue
            if active_filter == 'market_macro' and category not in {'macro', 'other'}:
                continue
            if not self._p34_article_matches_text_filter(article, query):
                continue
            (portfolio if category == 'portfolio' else market).append(article)
        portfolio.sort(key=lambda item: self._p34_numeric(item.get('_ts')), reverse=True)
        if hasattr(self, 'p34_sort_combo') and self.p34_sort_combo.currentText() == 'Signal':
            market.sort(
                key=lambda item: (
                    1 if '_trader_score' in item else 0,
                    self._p34_numeric(item.get('_trader_score')),
                    self._p34_numeric(item.get('_ts')),
                ),
                reverse=True,
            )
        else:
            market.sort(key=lambda item: self._p34_numeric(item.get('_ts')), reverse=True)
        return portfolio, market

    def _p34_clear_cards(self) -> None:
        for card in list(getattr(self, '_p34_cards_by_key', {}).values()):
            card.deleteLater()
        self._p34_ticker_search_cards = []
        self._p34_portfolio_cards = []
        self._p34_market_cards = []
        self._p34_cards_by_key = {}
        for grid in (self.p34_ticker_search_grid, self.p34_portfolio_grid, self.p34_market_grid):
            while grid.count():
                grid.takeAt(0)

    def _p34_make_transparent_to_mouse(self, widget: Any) -> Any:
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        return widget

    def _p34_create_card(self, article: dict[str, Any]) -> _NewsArticleCard:
        card = _NewsArticleCard(article)
        card.selected.connect(self._p34_set_highlighted_news)
        card.activated.connect(self._p34_open_article_external)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 9, 10, 9)
        card_layout.setSpacing(7)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        category = QLabel(self._p34_category_label(article))
        card.category_label = category
        category.setObjectName('newsCategory')
        category.setStyleSheet(f'font-weight: 700; color: {self.theme_color(self._p34_category_token(article))};')
        self._p34_make_transparent_to_mouse(category)
        ticker = QLabel(str(article.get('ticker') or '--'))
        card.ticker_label = ticker
        ticker.setObjectName('newsTicker')
        ticker.setStyleSheet(
            f'background: {self.theme_color("background_secondary")}; border: 1px solid {self.theme_color("panel_border")}; '
            f'border-radius: 4px; padding: 2px 6px; color: {self.theme_color("text_secondary")}; font-weight: 700;'
        )
        self._p34_make_transparent_to_mouse(ticker)
        age = QLabel(self._p34_article_age_text(article))
        card.age_label = age
        age.setStyleSheet(f'color: {self.theme_color("text_muted")};')
        self._p34_make_transparent_to_mouse(age)
        meta_row.addWidget(category)
        meta_row.addWidget(ticker)
        meta_row.addStretch()
        meta_row.addWidget(age)
        card_layout.addLayout(meta_row)

        headline = QLabel(str(article.get('title') or 'N/A'))
        card.headline_label = headline
        headline.setObjectName('newsHeadline')
        headline.setWordWrap(True)
        headline.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        headline.setStyleSheet(f'font-size: 13px; font-weight: 700; color: {self.theme_color("text_primary")};')
        self._p34_make_transparent_to_mouse(headline)
        card_layout.addWidget(headline)

        source = QLabel(f"Source: {str(article.get('source') or '--')}")
        card.source_label = source
        source.setWordWrap(True)
        source.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 11px;')
        self._p34_make_transparent_to_mouse(source)
        card_layout.addWidget(source)

        signals = self._p34_signal_text(article)
        score = article.get('_trader_score') if '_trader_score' in article else None
        signal_parts = []
        if signals:
            signal_parts.append(signals)
        if score is not None:
            signal_parts.append(f'Heuristic {score}')
        if signal_parts:
            signal_label = QLabel('  |  '.join(signal_parts))
            card.signal_label = signal_label
            signal_label.setWordWrap(True)
            signal_label.setStyleSheet(f'color: {self.theme_color("accent")}; font-size: 11px;')
            self._p34_make_transparent_to_mouse(signal_label)
            card_layout.addWidget(signal_label)

        action_row = QHBoxLayout()
        hint = QLabel('Click to read')
        card.hint_label = hint
        hint.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 10px;')
        self._p34_make_transparent_to_mouse(hint)
        open_button = QPushButton('Open ↗')
        open_button.setEnabled(bool(str(article.get('url') or '')))
        open_button.clicked.connect(lambda _checked=False, payload=dict(article): self._p34_open_article_external(payload))
        action_row.addWidget(hint)
        action_row.addStretch()
        action_row.addWidget(open_button)
        card_layout.addLayout(action_row)
        self._p34_style_card(card)
        return card

    def _p34_style_card(self, card: _NewsArticleCard) -> None:
        selected = self._p34_article_key(card.article) == self._p34_article_key(getattr(self, '_p34_highlighted_news', None))
        border = self.theme_color('accent') if selected else self.theme_color(self._p34_category_token(card.article))
        background = self.theme_color('selected_bg') if selected else self.theme_color('panel_background')
        width = 2 if selected else 1
        card.setProperty('bt_selected', selected)
        card.setStyleSheet(
            f'QFrame#newsArticleCard {{ background: {background}; border: {width}px solid {border}; border-radius: 7px; }}'
            'QFrame#newsArticleCard QLabel { border: none; background: transparent; }'
        )
        card.category_label.setStyleSheet(
            f'font-weight: 700; color: {self.theme_color(self._p34_category_token(card.article))};'
        )
        card.ticker_label.setStyleSheet(
            f'background: {self.theme_color("background_secondary")}; border: 1px solid {self.theme_color("panel_border")}; '
            f'border-radius: 4px; padding: 2px 6px; color: {self.theme_color("text_secondary")}; font-weight: 700;'
        )
        card.age_label.setStyleSheet(f'color: {self.theme_color("text_muted")};')
        card.headline_label.setStyleSheet(
            f'font-size: 13px; font-weight: 700; color: {self.theme_color("text_primary")};'
        )
        card.source_label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 11px;')
        if hasattr(card, 'signal_label'):
            card.signal_label.setStyleSheet(f'color: {self.theme_color("accent")}; font-size: 11px;')
        card.hint_label.setStyleSheet(f'color: {self.theme_color("text_muted")}; font-size: 10px;')

    def _p34_refresh_cards(self, *_args: Any) -> None:
        if not hasattr(self, 'p34_portfolio_grid'):
            return
        if not self._p34_page_is_visible():
            self._p34_render_pending = True
            return
        self._p34_render_pending = False
        highlighted_key = self._p34_article_key(getattr(self, '_p34_highlighted_news', None))
        ticker_search = self._p34_filtered_ticker_search_articles()
        portfolio, market = self._p34_filtered_groups()
        all_visible = ticker_search + portfolio + market
        self._p34_visible_articles = [dict(article) for article in all_visible]
        grouped_articles = [
            *(('ticker', article) for article in ticker_search),
            *(('portfolio', article) for article in portfolio),
            *(('market', article) for article in market),
        ]
        has_ticker_search = bool(
            getattr(self, '_p34_ticker_search_pending', False)
            or getattr(self, '_p34_ticker_search_tickers', [])
        )
        viewport_width = self.p34_cards_scroll.viewport().width() if hasattr(self, 'p34_cards_scroll') else 1050
        columns = self._p34_columns_for_width(viewport_width)
        self._p34_render_generation += 1
        generation = self._p34_render_generation
        prepared = False

        def _prepare() -> None:
            nonlocal prepared
            prepared = True
            self._p34_clear_cards()
            self._p34_card_columns = columns
            for grid in (self.p34_ticker_search_grid, self.p34_portfolio_grid, self.p34_market_grid):
                for column in range(3):
                    grid.setColumnStretch(column, 1 if column < columns else 0)

        def _apply(_index: int, grouped: tuple[str, dict[str, Any]]) -> None:
            group, article = grouped
            card = self._p34_create_card(article)
            if group == 'ticker':
                cards = self._p34_ticker_search_cards
                grid = self.p34_ticker_search_grid
            elif group == 'portfolio':
                cards = self._p34_portfolio_cards
                grid = self.p34_portfolio_grid
            else:
                cards = self._p34_market_cards
                grid = self.p34_market_grid
            group_index = len(cards)
            cards.append(card)
            self._p34_cards_by_key[self._p34_article_key(article)] = card
            grid.addWidget(card, group_index // columns, group_index % columns)

        def _finish() -> None:
            is_current = generation == self._p34_render_generation
            if is_current and not self._p34_page_is_visible():
                self._p34_render_pending = True
            if not prepared or not is_current or not self._p34_page_is_visible():
                return
            self.p34_ticker_search_section.setVisible(has_ticker_search)
            self.p34_portfolio_section.setVisible(bool(portfolio))
            self.p34_market_section.setVisible(bool(market))
            self._p34_update_ticker_search_summary()
            self._p34_update_counts(len(all_visible))
            visible_keys = {self._p34_article_key(article) for article in all_visible}
            if highlighted_key in visible_keys:
                selected = next(article for article in all_visible if self._p34_article_key(article) == highlighted_key)
            elif ticker_search:
                selected = ticker_search[0]
            elif portfolio:
                selected = portfolio[0]
            elif market:
                selected = market[0]
            else:
                selected = None
            self._p34_set_highlighted_news(selected, force=True)

        if (
            not callable(getattr(self, '_is_current_page', None))
            or len(grouped_articles) <= DEFAULT_MAX_ITEMS
        ):
            _prepare()
            try:
                for index, grouped in enumerate(grouped_articles):
                    _apply(index, grouped)
            finally:
                _finish()
            return

        run_batched(
            self,
            'news-cards',
            grouped_articles,
            _apply,
            generation=generation,
            prepare=_prepare,
            finish=_finish,
            is_current=lambda value: value == self._p34_render_generation,
            is_visible=self._p34_page_is_visible,
        )

    def _p34_update_counts(self, visible_count: int) -> None:
        loaded = getattr(self, '_p34_loaded_news', {})
        portfolio_count = len(loaded.get('portfolio', []))
        market_count = len(loaded.get('macro', [])) + len(loaded.get('other', []))
        ticker_search_count = len(getattr(self, '_p34_ticker_search_articles', []))
        total = portfolio_count + market_count + ticker_search_count
        labels = {
            'all': f'All ({total})',
            'portfolio': f'Portfolio ({portfolio_count})',
            'market_macro': f'Market & Macro ({market_count})',
        }
        for key, text in labels.items():
            button = getattr(self, 'p34_filter_buttons', {}).get(key)
            if button is not None:
                button.setText(text)
        if hasattr(self, 'p34_visible_count_lbl'):
            noun = 'article' if total == 1 else 'articles'
            suffix = f' ({ticker_search_count} ticker search)' if ticker_search_count else ''
            self.p34_visible_count_lbl.setText(f'{visible_count} visible of {total} {noun}{suffix}')

    def _p34_columns_for_width(self, width: int) -> int:
        if int(width) >= 1050:
            return 3
        if int(width) >= 700:
            return 2
        return 1

    def _p34_reflow_cards(self, width: int) -> None:
        columns = self._p34_columns_for_width(width)
        if columns == getattr(self, '_p34_card_columns', 0):
            return
        self._p34_card_columns = columns
        for grid, cards in (
            (self.p34_ticker_search_grid, self._p34_ticker_search_cards),
            (self.p34_portfolio_grid, self._p34_portfolio_cards),
            (self.p34_market_grid, self._p34_market_cards),
        ):
            while grid.count():
                grid.takeAt(0)
            for column in range(3):
                grid.setColumnStretch(column, 1 if column < columns else 0)
            for index, card in enumerate(cards):
                grid.addWidget(card, index // columns, index % columns)

    def _p34_set_highlighted_news(self, article: Any, *, force: bool = False) -> None:
        article_payload = dict(article) if isinstance(article, dict) else None
        current = getattr(self, '_p34_highlighted_news', None)
        if not force and article_payload and current and self._p34_article_key(article_payload) == self._p34_article_key(current):
            return
        self._p34_highlighted_news = article_payload
        for card in list(getattr(self, '_p34_cards_by_key', {}).values()):
            self._p34_style_card(card)
        self._p34_render_reader()

    def _p34_style_reader_category(self) -> None:
        label = getattr(self, 'p34_reader_category_lbl', None)
        if label is None:
            return
        article = getattr(self, '_p34_highlighted_news', None)
        token = self._p34_category_token(article) if article else 'text_muted'
        label.setStyleSheet(f'color: {self.theme_color(token)}; font-weight: 700;')

    def _p34_render_reader(self) -> None:
        article = getattr(self, '_p34_highlighted_news', None)
        if not isinstance(article, dict) or not article:
            self._p34_preview_request_id += 1
            self.p34_reader_category_lbl.setText('No story selected')
            self.p34_reader_title_lbl.setText('Select a news card to read it here')
            self.p34_reader_meta_lbl.setText('Ticker: -- | Source: -- | Age: --')
            self.p34_reader_url_lbl.setText('URL: --')
            self.p34_reader_body.setPlainText('Select a card to load a readable article preview.')
            self.p34_open_external_btn.setEnabled(False)
            self._p34_style_reader_category()
            return
        category = self._p34_category_label(article)
        title = escape(str(article.get('title') or 'N/A'))
        ticker = str(article.get('ticker') or '--')
        source = str(article.get('source') or '--')
        age = self._p34_article_age_text(article)
        signals = self._p34_signal_text(article)
        url = str(article.get('url') or '')
        self.p34_reader_category_lbl.setText(category)
        self.p34_reader_title_lbl.setText(f'<b>{title}</b>')
        meta = f'Ticker: {ticker} | Source: {source} | Age: {age}'
        if signals:
            meta += f' | Signals: {signals}'
        self.p34_reader_meta_lbl.setText(meta)
        self.p34_reader_url_lbl.setText(f'URL: {url or "--"}')
        self.p34_reader_body.setPlainText('Loading readable preview...')
        self.p34_open_external_btn.setEnabled(bool(url))
        self._p34_style_reader_category()
        self._p34_fetch_news_preview(dict(article))

    def _p34_fetch_news_preview(self, article: dict[str, Any]) -> None:
        self._p34_preview_request_id += 1
        request_id = self._p34_preview_request_id
        article_key = self._p34_article_key(article)

        def _run() -> None:
            result = build_news_preview_text(article)
            self._p34_preview_signals.preview_ready.emit(request_id, article_key, result)

        threading.Thread(target=_run, daemon=True).start()

    def _p34_on_preview_ready(self, request_id: int, article_key: object, result: object) -> None:
        if request_id != getattr(self, '_p34_preview_request_id', 0):
            return
        if self._p34_article_key(getattr(self, '_p34_highlighted_news', None)) != article_key:
            return
        if not self._p34_page_is_visible():
            self._p34_pending_preview = (request_id, article_key, result)
            return
        self._p34_pending_preview = None
        payload = result if isinstance(result, dict) else {}
        text = str(payload.get('text') or '').strip()
        error = str(payload.get('error') or '').strip()
        self.p34_reader_body.setPlainText(text or 'Preview unavailable. Open externally for the full article.')
        if error:
            logger.info('News preview unavailable: %s', error)
            self._p34_publish_status('Preview unavailable. Open externally for the full article.', 'warning')
            if hasattr(self, 'status_bar'):
                self.status_bar.setToolTip(error)

    def _p34_open_article_external(self, article: Any) -> None:
        url = str(article.get('url') or '') if isinstance(article, dict) else ''
        if not url:
            self._p34_set_status('No News URL to open.', 'warning')
            return
        logger.info('Opening News link: %s', url)
        webbrowser.open(url)

    def _p34_open_highlighted_news_external(self) -> None:
        self._p34_open_article_external(getattr(self, '_p34_highlighted_news', None))

    def update_page34(self, data: Any) -> None:
        """Update News from an existing dashboard or News-only payload."""
        news = data.get('news', []) if isinstance(data, dict) else []
        self._p34_loaded_news = {
            'portfolio': [dict(article) for article in news if article.get('category') == 'portfolio'],
            'macro': [dict(article) for article in news if article.get('category') == 'macro'],
            'other': [dict(article) for article in news if article.get('category') == 'other'],
        }
        self._p34_refresh_cards()

    def _p34_fetch_tickers(self) -> list[str]:
        get_fetch_tickers = getattr(self, '_get_fetch_tickers', None)
        if callable(get_fetch_tickers):
            return list(get_fetch_tickers())
        return list(getattr(self, 'tickers', []) or [])

    def _p34_emit_main(self, fn: Any) -> None:
        signal = getattr(self, '_invoke_main', None)
        if signal is not None and hasattr(signal, 'emit'):
            signal.emit(fn)
        else:
            fn()

    def _p34_parse_ticker_search_symbols(self, text: Any) -> list[str]:
        symbols = []
        seen = set()
        for token in re.split(r'[\s,;]+', str(text or '')):
            symbol = token.upper().strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
            if len(symbols) >= 10:
                break
        return symbols

    def _p34_update_ticker_search_summary(self) -> None:
        tickers = list(getattr(self, '_p34_ticker_search_tickers', []))
        articles = list(getattr(self, '_p34_ticker_search_articles', []))
        empty_tickers = list(getattr(self, '_p34_ticker_search_empty_tickers', []))
        failed_tickers = list(getattr(self, '_p34_ticker_search_failed_tickers', []))
        if getattr(self, '_p34_ticker_search_pending', False):
            text = f"Searching exact ticker news for {', '.join(tickers)}..."
        elif tickers:
            noun = 'article' if len(articles) == 1 else 'articles'
            parts = [f"Queried: {', '.join(tickers)}", f'{len(articles)} {noun}']
            if empty_tickers:
                parts.append(f"No articles: {', '.join(empty_tickers)}")
            if failed_tickers:
                parts.append(f"Failed: {', '.join(failed_tickers)}")
            text = ' · '.join(parts)
        else:
            text = 'Searches are temporary and do not change your portfolio.'
        if hasattr(self, 'p34_ticker_search_status_lbl'):
            self.p34_ticker_search_status_lbl.setText(text)
        if hasattr(self, 'p34_ticker_search_meta_lbl'):
            self.p34_ticker_search_meta_lbl.setText(text if tickers else '')

    def _p34_request_ticker_search(self) -> None:
        text = self.p34_ticker_search_input.text() if hasattr(self, 'p34_ticker_search_input') else ''
        tickers = self._p34_parse_ticker_search_symbols(text)
        if not tickers:
            self._p34_set_status('Enter at least one ticker to search.', 'warning')
            return
        self._p34_ticker_search_request_id = int(getattr(self, '_p34_ticker_search_request_id', 0) or 0) + 1
        request_id = self._p34_ticker_search_request_id
        self._p34_ticker_search_pending = True
        self._p34_ticker_search_tickers = list(tickers)
        self._p34_ticker_search_articles = []
        self._p34_ticker_search_empty_tickers = []
        self._p34_ticker_search_failed_tickers = []
        self._p34_refresh_cards()
        self._p34_set_status(f"Searching ticker news for {', '.join(tickers)}...", 'info')
        executor_factory = getattr(self, '_ensure_dashboard_fetch_executor', None)
        if not callable(executor_factory):
            self._p34_handle_ticker_search_error(request_id, 'Ticker search executor is unavailable.')
            return
        self._p34_ticker_search_future = executor_factory().submit(
            self._p34_run_ticker_search,
            request_id,
            tickers,
        )

    def _p34_run_ticker_search(self, request_id: int, tickers: list[str]) -> None:
        try:
            cache_manager_factory = getattr(self, '_get_cache_manager', None)
            worker = DataWorker(
                tickers,
                [],
                request_id=request_id,
                cancel_check=lambda req=request_id: req != getattr(self, '_p34_ticker_search_request_id', 0),
                cache_manager=cache_manager_factory() if callable(cache_manager_factory) else None,
                refresh_reason=NEWS_PAGE_REFRESH_REASON,
                allow_non_chart_reuse=False,
            )
            result = worker.fetch_ticker_news_only(max_per_ticker=3)
            self._p34_emit_main(
                lambda payload=result, req=request_id: self._p34_apply_ticker_search_result(req, payload)
            )
        except Exception as exc:
            logger.error('News ticker search failed: %s', exc)
            self._p34_emit_main(
                lambda msg=str(exc), req=request_id: self._p34_handle_ticker_search_error(req, msg)
            )

    def _p34_apply_ticker_search_result(self, request_id: int, result: Any) -> None:
        if request_id != int(getattr(self, '_p34_ticker_search_request_id', 0) or 0):
            return
        payload = result if isinstance(result, dict) else {}
        queried = [str(ticker or '').upper().strip() for ticker in payload.get('queried_tickers', []) if str(ticker or '').strip()]
        articles = []
        for article in payload.get('articles', []):
            if not isinstance(article, dict):
                continue
            searched_article = dict(article)
            searched_article['category'] = 'search'
            articles.append(searched_article)
        articles.sort(key=lambda article: self._p34_numeric(article.get('_ts')), reverse=True)
        self._p34_ticker_search_pending = False
        self._p34_ticker_search_tickers = queried or list(getattr(self, '_p34_ticker_search_tickers', []))
        self._p34_ticker_search_articles = articles
        self._p34_ticker_search_empty_tickers = [
            str(ticker or '').upper().strip()
            for ticker in payload.get('empty_tickers', [])
            if str(ticker or '').strip()
        ]
        self._p34_ticker_search_failed_tickers = [
            str(ticker or '').upper().strip()
            for ticker in payload.get('failed_tickers', [])
            if str(ticker or '').strip()
        ]
        if articles:
            self._p34_highlighted_news = dict(articles[0])
        self._p34_refresh_cards()
        notes = []
        if self._p34_ticker_search_empty_tickers:
            notes.append(f"no articles for {', '.join(self._p34_ticker_search_empty_tickers)}")
        if self._p34_ticker_search_failed_tickers:
            notes.append(f"failed: {', '.join(self._p34_ticker_search_failed_tickers)}")
        suffix = f" ({'; '.join(notes)})" if notes else ''
        status = 'positive' if articles and not notes else 'warning'
        self._p34_publish_status(f'Ticker search returned {len(articles)} article(s).{suffix}', status)

    def _p34_handle_ticker_search_error(self, request_id: int, message: Any) -> None:
        if request_id != int(getattr(self, '_p34_ticker_search_request_id', 0) or 0):
            return
        self._p34_ticker_search_pending = False
        self._p34_ticker_search_articles = []
        self._p34_ticker_search_empty_tickers = []
        self._p34_ticker_search_failed_tickers = list(getattr(self, '_p34_ticker_search_tickers', []))
        self._p34_refresh_cards()
        self._p34_publish_status(f'Ticker search failed: {str(message or "Unknown error")}', 'negative')

    def _p34_clear_ticker_search(self) -> None:
        selected = getattr(self, '_p34_highlighted_news', None)
        selected_search = isinstance(selected, dict) and selected.get('category') == 'search'
        self._p34_ticker_search_request_id = int(getattr(self, '_p34_ticker_search_request_id', 0) or 0) + 1
        self._p34_ticker_search_pending = False
        self._p34_ticker_search_tickers = []
        self._p34_ticker_search_articles = []
        self._p34_ticker_search_empty_tickers = []
        self._p34_ticker_search_failed_tickers = []
        if hasattr(self, 'p34_ticker_search_input'):
            self.p34_ticker_search_input.clear()
        if selected_search:
            self._p34_highlighted_news = None
        self._p34_refresh_cards()
        self._p34_set_status('Ticker search cleared.', 'info')

    def _p34_request_news_refresh(self) -> bool:
        tickers = self._p34_fetch_tickers()
        signature = tuple(str(ticker or '').upper().strip() for ticker in tickers if str(ticker or '').strip())
        if getattr(self, '_p34_news_refresh_pending', False):
            if signature != getattr(self, '_p34_news_refresh_signature', ()):
                self._p34_news_refresh_queued_tickers = list(tickers)
            else:
                self._p34_news_refresh_queued_tickers = None
            return False
        self._p34_start_news_refresh(tickers)
        return True

    def _p34_start_news_refresh(self, tickers: list[str]) -> None:
        self._p34_news_refresh_request_id = int(getattr(self, '_p34_news_refresh_request_id', 0) or 0) + 1
        request_id = self._p34_news_refresh_request_id
        self._p34_news_refresh_pending = True
        self._p34_news_refresh_signature = tuple(
            str(ticker or '').upper().strip() for ticker in tickers if str(ticker or '').strip()
        )
        self._p34_publish_status('Refreshing News...', 'info')
        executor_factory = getattr(self, '_ensure_dashboard_fetch_executor', None)
        if not callable(executor_factory):
            self._p34_handle_news_refresh_error(request_id, 'News refresh executor is unavailable.')
            return
        self._p34_news_refresh_future = executor_factory().submit(
            self._p34_run_news_refresh,
            request_id,
            list(tickers),
        )

    def _p34_start_queued_news_refresh(self) -> bool:
        queued = getattr(self, '_p34_news_refresh_queued_tickers', None)
        self._p34_news_refresh_queued_tickers = None
        if queued is None:
            self._p34_news_refresh_signature = ()
            return False
        self._p34_news_refresh_pending = False
        self._p34_start_news_refresh(list(queued))
        return True

    def _p34_run_news_refresh(self, request_id: int, tickers: list[str]) -> None:
        try:
            data = None
            client = getattr(self, '_data_service_client', None)
            if client is None:
                wait_for_client = getattr(self, '_dashboard_wait_for_data_service_client', None)
                if callable(wait_for_client):
                    client = wait_for_client()
            if client is not None:
                try:
                    data = client.fetch_dashboard(
                        tickers,
                        [],
                        request_id=request_id,
                        refresh_reason=NEWS_PAGE_REFRESH_REASON,
                        allow_non_chart_reuse=False,
                    )
                except Exception as exc:
                    logger.warning('Embedded data service News refresh failed; falling back to direct worker: %s', exc)
            if data is None:
                cache_manager_factory = getattr(self, '_get_cache_manager', None)
                worker = DataWorker(
                    tickers,
                    [],
                    request_id=request_id,
                    cancel_check=lambda req=request_id: req != getattr(self, '_p34_news_refresh_request_id', 0),
                    cache_manager=cache_manager_factory() if callable(cache_manager_factory) else None,
                    refresh_reason=NEWS_PAGE_REFRESH_REASON,
                    allow_non_chart_reuse=False,
                )
                data = worker.fetch()
            if data is not None:
                self._p34_emit_main(lambda payload=data, req=request_id: self._p34_apply_news_refresh_result(req, payload))
            else:
                self._p34_emit_main(lambda req=request_id: self._p34_handle_news_refresh_error(req, 'News worker returned no data.'))
        except Exception as exc:
            logger.error('News refresh failed: %s', exc)
            self._p34_emit_main(lambda msg=str(exc), req=request_id: self._p34_handle_news_refresh_error(req, msg))

    def _p34_merge_news_refresh_data(self, data: Any) -> list[dict[str, Any]]:
        news = [dict(article) for article in (data.get('news', []) if isinstance(data, dict) else [])]
        current = getattr(self, 'last_data', None)
        if isinstance(current, dict):
            merged = dict(current)
            merged['news'] = [dict(article) for article in news]
            self.last_data = merged
        elif isinstance(data, dict):
            self.last_data = dict(data)
        return news

    def _p34_apply_news_refresh_result(self, request_id: int, data: Any) -> None:
        if request_id != int(getattr(self, '_p34_news_refresh_request_id', 0) or 0):
            return
        if self._p34_start_queued_news_refresh():
            return
        self._p34_news_refresh_pending = False
        self._p34_news_refresh_signature = ()
        refresh_meta = dict(data.get('_news_refresh_meta', {})) if isinstance(data, dict) else {}
        news = self._p34_merge_news_refresh_data(data)
        logger.info('Applying News refresh %s with %s article(s).', request_id, len(news))
        self.update_page34({'news': news})
        stale_sources = set(refresh_meta.get('stale_sources', []))
        failed_sources = set(refresh_meta.get('failed_sources', []))
        unavailable_sources = failed_sources - stale_sources
        failed_tickers = set(refresh_meta.get('failed_tickers', []))
        notes = []
        if stale_sources:
            notes.append(f'{len(stale_sources)} stale source(s)')
        if unavailable_sources:
            notes.append(f'{len(unavailable_sources)} unavailable source(s)')
        if failed_tickers:
            notes.append(f'{len(failed_tickers)} ticker search failure(s)')
        suffix = f" ({', '.join(notes)})" if notes else ''
        status = 'positive' if news and not notes else 'warning'
        self._p34_publish_status(f'News refreshed: {len(news)} article(s).{suffix}', status)

    def _p34_handle_news_refresh_error(self, request_id: int, message: Any) -> None:
        if request_id != int(getattr(self, '_p34_news_refresh_request_id', 0) or 0):
            return
        if self._p34_start_queued_news_refresh():
            return
        self._p34_news_refresh_pending = False
        self._p34_news_refresh_signature = ()
        self._p34_publish_status(f'News refresh failed: {str(message or "Unknown error")}', 'negative')

    def _p34_downloads_directory(self) -> Path:
        standard_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        directory = Path(standard_path) if standard_path else Path.home() / 'Downloads'
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _p34_next_export_path(self, *, now: Any = None, directory: Any = None) -> Path:
        exported_at = now if isinstance(now, datetime.datetime) else datetime.datetime.now().astimezone()
        root = Path(directory) if directory is not None else self._p34_downloads_directory()
        root.mkdir(parents=True, exist_ok=True)
        base_name = f'BudgetTerminal_News_{exported_at.strftime("%Y-%m-%d_%H%M%S")}'
        path = root / f'{base_name}.txt'
        suffix = 2
        while path.exists():
            path = root / f'{base_name}_{suffix}.txt'
            suffix += 1
        return path

    def _p34_published_text(self, article: dict[str, Any]) -> str:
        timestamp = self._p34_numeric(article.get('_ts'))
        if timestamp <= 0:
            return 'Unknown'
        try:
            return datetime.datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec='seconds')
        except (OSError, OverflowError, ValueError):
            return 'Unknown'

    def _p34_export_section_lines(self, heading: str, articles: list[dict[str, Any]]) -> list[str]:
        lines = [f'=== {heading.upper()} ===', '']
        ordered = sorted(articles, key=lambda item: self._p34_numeric(item.get('_ts')), reverse=True)
        if not ordered:
            return lines + ['(No articles loaded.)', '']
        for index, article in enumerate(ordered, start=1):
            category = self._p34_category_label(article)
            ticker = str(article.get('ticker') or '--')
            title = str(article.get('title') or 'N/A')
            source = str(article.get('source') or '--')
            url = str(article.get('url') or '')
            signals = self._p34_signal_text(article)
            lines.append(f'{index}. [{category}] [{ticker}] {title}')
            lines.append(f'   Source: {source}')
            lines.append(f'   Published: {self._p34_published_text(article)}')
            lines.append(f'   Age: {self._p34_article_age_text(article)}')
            if signals:
                lines.append(f'   Signals: {signals}')
            if '_trader_score' in article:
                lines.append(f'   Heuristic score: {article.get("_trader_score", 0)}')
            if url:
                lines.append(f'   URL: {url}')
            lines.append('')
        return lines

    def _p34_build_export_text(self, *, now: Any = None) -> str:
        exported_at = now if isinstance(now, datetime.datetime) else datetime.datetime.now().astimezone()
        if exported_at.tzinfo is None:
            exported_at = exported_at.astimezone()
        loaded = getattr(self, '_p34_loaded_news', {})
        searched_tickers = list(getattr(self, '_p34_ticker_search_tickers', []))
        searched = [dict(article) for article in getattr(self, '_p34_ticker_search_articles', [])]
        portfolio = [dict(article) for article in loaded.get('portfolio', [])]
        market = [dict(article) for article in loaded.get('macro', [])] + [
            dict(article) for article in loaded.get('other', [])
        ]
        total = len(searched) + len(portfolio) + len(market)
        if searched_tickers or searched:
            coverage = (
                f'Coverage: {len(searched)} ticker search article(s); {len(portfolio)} portfolio article(s); '
                f'{len(market)} market and macro article(s); {total} total.'
            )
        else:
            coverage = (
                f'Coverage: {len(portfolio)} portfolio article(s); {len(market)} market and macro article(s); '
                f'{total} total.'
            )
        lines = [
            NEWS_AI_PROMPT,
            '',
            f'Generated at: {exported_at.isoformat(timespec="seconds")}',
            coverage,
            '',
        ]
        if searched_tickers or searched:
            lines.extend([f"Searched tickers: {', '.join(searched_tickers) or '--'}", ''])
            lines.extend(self._p34_export_section_lines('Ticker Search Results', searched))
        lines.extend(self._p34_export_section_lines('Portfolio News', portfolio))
        lines.extend(self._p34_export_section_lines('Market & Macro News', market))
        return '\n'.join(lines).rstrip() + '\n'

    def _p34_write_export_file(self, path: Path, text: str) -> None:
        path.write_text(text, encoding='utf-8')

    def _p34_export_news_for_ai(self) -> None:
        total = sum(len(items) for items in getattr(self, '_p34_loaded_news', {}).values())
        total += len(getattr(self, '_p34_ticker_search_articles', []))
        if total <= 0:
            self._p34_set_status('No News articles to export.', 'warning')
            return
        try:
            path = self._p34_next_export_path()
            self._p34_write_export_file(path, self._p34_build_export_text())
        except Exception as exc:
            QMessageBox.critical(self, 'Export Failed', f'Unable to export News to Downloads.\n\n{exc}')
            self._p34_set_status(f'News export failed: {exc}', 'negative')
            return
        self._p34_set_status(f'Exported {total} News article(s) to {path}', 'positive')
