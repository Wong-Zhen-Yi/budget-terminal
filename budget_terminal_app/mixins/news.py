from __future__ import annotations

from typing import Any

from ..compat import *


class NewsMixin:

    def _sort_articles_by_newest(self, articles: Any) -> Any:
        """Return newest articles first."""
        return sorted(articles, key=lambda article: article.get('_ts', 0), reverse=True)

    def _make_news_table(self, on_click: Any) -> Any:
        """Factory: create a standard 4-column news QTableWidget."""
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(['Headline', 'Ticker', 'Source', 'Time'])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in range(1, 4):
            table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setWordWrap(True)
        table.itemClicked.connect(lambda item, tbl=table: on_click(item, tbl))
        return table

    def init_page3(self) -> None:
        """Build the News page UI."""
        self._p3_loaded_news = {'portfolio': [], 'macro': [], 'other': []}

        layout = QVBoxLayout(self.page3)
        layout.setContentsMargins(10, 10, 10, 4)
        layout.setSpacing(6)
        panels_row = QHBoxLayout()
        panels_row.setSpacing(6)

        portfolio_box = QGroupBox('Portfolio News')
        self.set_theme_role(portfolio_box, 'panel')
        portfolio_layout = QVBoxLayout(portfolio_box)
        portfolio_layout.setContentsMargins(4, 8, 4, 4)
        portfolio_layout.setSpacing(6)
        self.p3_portfolio_table = self._make_news_table(self._open_news_link_table)
        portfolio_layout.addWidget(self.p3_portfolio_table, 1)
        self.p3_export_portfolio_news_btn = QPushButton('Export Portfolio News')
        self.set_theme_variant(self.p3_export_portfolio_news_btn, 'positive')
        self.p3_export_portfolio_news_btn.clicked.connect(self._p3_export_portfolio_news)
        portfolio_layout.addWidget(self.p3_export_portfolio_news_btn)
        panels_row.addWidget(portfolio_box, 1)

        macro_box = QGroupBox('Market && Macro News')
        self.set_theme_role(macro_box, 'panel')
        macro_layout = QVBoxLayout(macro_box)
        macro_layout.setContentsMargins(4, 8, 4, 4)
        macro_layout.setSpacing(6)
        self.p3_macro_table = self._make_news_table(self._open_news_link_table)
        macro_layout.addWidget(self.p3_macro_table, 1)
        self.p3_export_macro_news_btn = QPushButton('Export Market && Macro News')
        self.set_theme_variant(self.p3_export_macro_news_btn, 'positive')
        self.p3_export_macro_news_btn.clicked.connect(self._p3_export_macro_news)
        macro_layout.addWidget(self.p3_export_macro_news_btn)
        panels_row.addWidget(macro_box, 1)

        other_box = QGroupBox('Other')
        self.set_theme_role(other_box, 'panel')
        other_layout = QVBoxLayout(other_box)
        other_layout.setContentsMargins(4, 8, 4, 4)
        other_layout.setSpacing(6)
        self.p3_other_table = self._make_news_table(self._open_news_link_table)
        other_layout.addWidget(self.p3_other_table, 1)
        self.p3_export_other_news_btn = QPushButton('Export Other News')
        self.set_theme_variant(self.p3_export_other_news_btn, 'positive')
        self.p3_export_other_news_btn.clicked.connect(self._p3_export_other_news)
        other_layout.addWidget(self.p3_export_other_news_btn)
        panels_row.addWidget(other_box, 1)

        layout.addLayout(panels_row, 1)

    def _apply_news_theme(self) -> None:
        """Refresh theme-dependent news page widgets."""
        return

    def _p3_set_status(self, text: str, status: str) -> None:
        """Mirror News page status updates into the shared footer."""
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=status)

    def _open_news_link_table(self, item: Any, table: Any) -> None:
        """Open the clicked news article."""
        row = item.row()
        headline_item = table.item(row, 0)
        if headline_item:
            url = headline_item.data(Qt.ItemDataRole.UserRole)
            if url:
                logger.info('Opening news link: %s', url)
                webbrowser.open(url)

    def _p3_build_export_text(self, heading: str, articles: list[dict[str, Any]]) -> str:
        """Build plain-text clipboard export content for one news section."""
        lines = [f'=== {heading.upper()} ===', '']
        for article in self._sort_articles_by_newest(articles):
            ticker = article.get('ticker', '')
            title = article.get('title', 'N/A')
            source = article.get('source', '')
            time_str = article.get('time', '')
            url = article.get('url', '')
            lines.append(f'[{ticker}] {title}')
            meta = []
            if source:
                meta.append(f'Source: {source}')
            if time_str:
                meta.append(f'Time: {time_str}')
            if url:
                meta.append(f'URL: {url}')
            if meta:
                lines.append('  ' + ' | '.join(meta))
            lines.append('')
        return '\n'.join(lines)

    def _p3_export_news_section(self, category: str, heading: str) -> None:
        """Export one loaded news section to the clipboard."""
        articles = list(self._p3_loaded_news.get(category, []))
        if not articles:
            self._p3_set_status(f'No {heading.lower()} to export.', 'warning')
            return
        try:
            QApplication.clipboard().setText(self._p3_build_export_text(heading, articles))
        except Exception as exc:
            QMessageBox.critical(self, 'Export Failed', f'Unable to copy {heading.lower()} to the clipboard.\n\n{exc}')
            self._p3_set_status(f'{heading} export failed: {exc}', 'negative')
            return
        self._p3_set_status(f'Exported {len(articles)} {heading.lower()} article(s) to clipboard', 'positive')

    def _p3_export_portfolio_news(self) -> None:
        """Export the portfolio news section to the clipboard."""
        self._p3_export_news_section('portfolio', 'Portfolio News')

    def _p3_export_macro_news(self) -> None:
        """Export the market and macro news section to the clipboard."""
        self._p3_export_news_section('macro', 'Market & Macro News')

    def _p3_export_other_news(self) -> None:
        """Export the other news section to the clipboard."""
        self._p3_export_news_section('other', 'Other News')

    def _populate_news_table(self, table: Any, articles: Any) -> None:
        """Populate one of the News page tables."""
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
        """Update the News page tables."""
        news = data.get('news', [])
        portfolio_news = self._sort_articles_by_newest([article for article in news if article.get('category') == 'portfolio'])
        macro_news = self._sort_articles_by_newest([article for article in news if article.get('category') == 'macro'])
        other_news = self._sort_articles_by_newest([
            article for article in news
            if article.get('category') not in ('portfolio', 'macro')
        ])
        self._p3_loaded_news = {
            'portfolio': [dict(article) for article in portfolio_news],
            'macro': [dict(article) for article in macro_news],
            'other': [dict(article) for article in other_news],
        }
        self._populate_news_table(self.p3_portfolio_table, portfolio_news)
        self._populate_news_table(self.p3_macro_table, macro_news)
        self._populate_news_table(self.p3_other_table, other_news)
