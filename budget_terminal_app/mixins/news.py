from __future__ import annotations
from typing import Any
from ..compat import *


class NewsMixin:

    def _sort_articles_by_newest(self, articles: Any) -> Any:
        """Return newest articles first."""
        return sorted(articles, key=lambda article: article.get('_ts', 0), reverse=True)

    def _make_news_table(self, on_click: Any, on_row_selected: Any=None) -> Any:
        """Factory: create a standard 4-column news QTableWidget."""
        t = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(['Headline', 'Ticker', 'Source', 'Time'])
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 4):
            t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        t.setWordWrap(True)
        t.itemClicked.connect(lambda item, tbl=t: on_click(item, tbl))
        if on_row_selected:
            t.clicked.connect(lambda idx, tbl=t: on_row_selected(idx.row(), tbl))
        return t

    def init_page3(self) -> None:
        """Build the News Hub page UI."""
        self._p3_loaded_news = {'portfolio': [], 'macro': []}
        layout = QVBoxLayout(self.page3)
        layout.setContentsMargins(10, 10, 10, 4)
        layout.setSpacing(6)
        panels_row = QHBoxLayout()

        portfolio_box = QGroupBox('Portfolio News')
        portfolio_box.setStyleSheet('QGroupBox { font-weight: bold; color: #aaa; }')
        portfolio_layout = QVBoxLayout(portfolio_box)
        portfolio_layout.setContentsMargins(4, 8, 4, 4)
        self.p3_portfolio_table = self._make_news_table(self._open_news_link_table, on_row_selected=self._on_news_row_selected)
        portfolio_layout.addWidget(self.p3_portfolio_table)
        panels_row.addWidget(portfolio_box, 1)

        macro_box = QGroupBox('Market && Macro News')
        macro_box.setStyleSheet('QGroupBox { font-weight: bold; color: #aaa; }')
        macro_layout = QVBoxLayout(macro_box)
        macro_layout.setContentsMargins(4, 8, 4, 4)
        self.p3_macro_table = self._make_news_table(self._open_news_link_table, on_row_selected=self._on_news_row_selected)
        macro_layout.addWidget(self.p3_macro_table)
        panels_row.addWidget(macro_box, 1)

        summarizer_box = QGroupBox('News Briefing')
        summarizer_box.setStyleSheet('QGroupBox { font-weight: bold; color: #aaa; }')
        summarizer_layout = QVBoxLayout(summarizer_box)
        summarizer_layout.setContentsMargins(6, 10, 6, 6)
        summarizer_layout.setSpacing(6)
        self.p3_summary_text = QTextEdit()
        self.p3_summary_text.setReadOnly(True)
        self.p3_summary_text.setStyleSheet('QTextEdit { background: #0d0d1f; color: #ddd; border: 1px solid #333; border-radius: 4px; font-size: 12px; padding: 6px; }')
        self.p3_summary_text.setPlaceholderText("Click a headline to analyze it, or press 'Generate Briefing' for a full summary.")
        summarizer_layout.addWidget(self.p3_summary_text, 1)
        self.p3_summary_status = QLabel('')
        self.p3_summary_status.setStyleSheet('color: #888; font-size: 11px;')
        self.p3_summary_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summarizer_layout.addWidget(self.p3_summary_status)
        summarize_all_btn = QPushButton('Generate Briefing')
        summarize_all_btn.setStyleSheet('QPushButton { background: #1a3a5c; color: #7ec8f7; border: 1px solid #2a5a8c; border-radius: 4px; padding: 5px; font-weight: bold; }QPushButton:hover { background: #1e4a7a; }QPushButton:disabled { color: #555; border-color: #333; }')
        summarize_all_btn.clicked.connect(self._summarize_all_news)
        summarizer_layout.addWidget(summarize_all_btn)
        self._p3_summarizing = False
        panels_row.addWidget(summarizer_box, 1)
        layout.addLayout(panels_row, 1)

        crawler_container = QWidget()
        crawler_container.setFixedHeight(28)
        crawler_container.setStyleSheet('background-color: #1a1a2e;')
        crawler_container.setMinimumWidth(0)
        crawler_outer = QHBoxLayout(crawler_container)
        crawler_outer.setContentsMargins(0, 0, 0, 0)
        self.p3_crawler_scroll = QScrollArea()
        self.p3_crawler_scroll.setFixedHeight(28)
        self.p3_crawler_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p3_crawler_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p3_crawler_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p3_crawler_scroll.setStyleSheet('background-color: #1a1a2e;')
        self.p3_crawler_label = QLabel('  Waiting for news...  ')
        self.p3_crawler_label.setStyleSheet('color: #ffd700; background-color: #1a1a2e; font-family: monospace; font-weight: bold; font-size: 13px;')
        self.p3_crawler_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.p3_crawler_label.adjustSize()
        self.p3_crawler_scroll.setWidget(self.p3_crawler_label)
        crawler_outer.addWidget(self.p3_crawler_scroll)
        layout.addWidget(crawler_container)
        self._crawler_offset = 0
        self.p3_crawler_timer = QTimer()
        self.p3_crawler_timer.timeout.connect(self._scroll_crawler)

    def _scroll_crawler(self) -> None:
        """Handle scroll crawler."""
        label_w = self.p3_crawler_label.sizeHint().width()
        viewport_w = self.p3_crawler_scroll.viewport().width()
        if label_w <= 0:
            return
        self._crawler_offset += 2
        if self._crawler_offset > label_w:
            self._crawler_offset = -viewport_w
        self.p3_crawler_scroll.horizontalScrollBar().setValue(int(self._crawler_offset))

    def _open_news_link_table(self, item: Any, table: Any) -> None:
        """Handle open news link table."""
        row = item.row()
        headline_item = table.item(row, 0)
        if headline_item:
            url = headline_item.data(Qt.ItemDataRole.UserRole)
            if url:
                logger.info(f'Opening news link: {url}')
                webbrowser.open(url)

    def _article_from_row(self, table: Any, row: Any) -> Any:
        """Return the stored article for a news table row."""
        if row < 0 or table.rowCount() == 0:
            return None
        headline_item = table.item(row, 0)
        if not headline_item:
            return None
        article = headline_item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(article, dict):
            return dict(article)
        return None

    def _on_news_row_selected(self, row: Any, table: Any) -> None:
        """Handle news row selected."""
        article = self._article_from_row(table, row)
        if not article:
            return
        self._run_summarizer([article])

    def _summarize_all_news(self) -> None:
        """Handle summarize all news."""
        articles = list(self._p3_loaded_news.get('portfolio', [])) + list(self._p3_loaded_news.get('macro', []))
        if not articles:
            self.p3_summary_text.setPlainText('No news loaded yet.')
            return
        self._run_summarizer(articles)

    def _run_summarizer(self, articles: Any) -> None:
        """Handle run summarizer."""
        if self._p3_summarizing:
            return
        self._p3_summarizing = True
        label = articles[0]['title'][:55] + '...' if len(articles) == 1 else f'{len(articles)} articles'
        self.p3_summary_status.setText(f'Analyzing: {label}')
        self.p3_summary_text.setPlainText('Analyzing headlines...')
        self._summarizer_worker = NewsSummarizerWorker(articles)
        self._summarizer_worker.finished.connect(self._on_summary_ready)
        self._summarizer_worker.error.connect(self._on_summary_error)
        threading.Thread(target=self._summarizer_worker.run, daemon=True).start()

    def _on_summary_ready(self, text: Any) -> None:
        """Handle summary ready."""
        self._p3_summarizing = False
        self.p3_summary_text.setPlainText(text)
        self.p3_summary_status.setText('')

    def _on_summary_error(self, err: Any) -> None:
        """Handle summary error."""
        self._p3_summarizing = False
        self.p3_summary_text.setPlainText(f'Error: {err}')
        self.p3_summary_status.setText('Summary failed.')

    def _populate_news_table(self, table: Any, articles: Any) -> None:
        """Handle populate news table."""
        table.setRowCount(0)
        for article in self._sort_articles_by_newest(articles):
            row = table.rowCount()
            table.insertRow(row)
            headline = article.get('title', 'N/A')
            url = article.get('url', '')
            headline_item = QTableWidgetItem(headline)
            headline_item.setData(Qt.ItemDataRole.UserRole, url)
            headline_item.setData(Qt.ItemDataRole.UserRole + 1, dict(article))
            headline_item.setToolTip(headline)
            table.setItem(row, 0, headline_item)

            ticker_item = QTableWidgetItem(article.get('ticker', ''))
            ticker_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 1, ticker_item)

            source_item = QTableWidgetItem(article.get('source', ''))
            source_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 2, source_item)

            time_item = QTableWidgetItem(article.get('time', ''))
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 3, time_item)
        table.clearSelection()
        table.setCurrentCell(-1, -1)
        table.scrollToTop()

    def update_page3(self, data: Any) -> None:
        """Update page3."""
        news = data.get('news', [])
        portfolio_news = self._sort_articles_by_newest([a for a in news if a.get('category') == 'portfolio'])
        macro_news = self._sort_articles_by_newest([a for a in news if a.get('category') == 'macro'])
        self._p3_loaded_news = {'portfolio': [dict(a) for a in portfolio_news], 'macro': [dict(a) for a in macro_news]}
        self._populate_news_table(self.p3_portfolio_table, portfolio_news)
        self._populate_news_table(self.p3_macro_table, macro_news)
        all_headlines = '   |   '.join((a['title'] for a in news if a.get('title')))
        self.p3_crawler_label.setText('  ' + all_headlines + '  ')
        self.p3_crawler_label.adjustSize()
        self._crawler_offset = 0
        if not self._news_auto_summarized and news:
            self._news_auto_summarized = True
            QTimer.singleShot(300, self._summarize_all_news)
