from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.workers.news import NewsSummarizerWorker


class NewsMixin:

    def _set_news_summary_idle_state(self, total_headlines: int = 0) -> None:
        """Reset the summary pane to the built-in rule-based state."""
        if getattr(self, '_p3_summarizing', False):
            return
        if total_headlines > 0:
            self.p3_summary_text.setPlainText(
                f"Loaded {total_headlines} headlines.\n\n"
                'The built-in news briefing refreshes automatically after news updates.\n'
                "Press 'Generate Briefing' to rerun the full digest, or select a headline row for a single-item summary.\n\n"
                'This summary uses headline wording only and does not inspect article bodies.'
            )
        else:
            self.p3_summary_text.setPlainText('No news loaded yet.')
        self.p3_summary_status.setText('')

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
        self._p3_pending_summary_articles = None
        self._p3_pending_summary_auto = False
        layout = QVBoxLayout(self.page3)
        layout.setContentsMargins(10, 10, 10, 4)
        layout.setSpacing(6)
        panels_row = QHBoxLayout()

        portfolio_box = QGroupBox('Portfolio News')
        self.set_theme_role(portfolio_box, 'panel')
        portfolio_layout = QVBoxLayout(portfolio_box)
        portfolio_layout.setContentsMargins(4, 8, 4, 4)
        self.p3_portfolio_table = self._make_news_table(self._open_news_link_table, on_row_selected=self._on_news_row_selected)
        portfolio_layout.addWidget(self.p3_portfolio_table)
        panels_row.addWidget(portfolio_box, 1)

        macro_box = QGroupBox('Market && Macro News')
        self.set_theme_role(macro_box, 'panel')
        macro_layout = QVBoxLayout(macro_box)
        macro_layout.setContentsMargins(4, 8, 4, 4)
        self.p3_macro_table = self._make_news_table(self._open_news_link_table, on_row_selected=self._on_news_row_selected)
        macro_layout.addWidget(self.p3_macro_table)
        panels_row.addWidget(macro_box, 1)

        summarizer_box = QGroupBox('News Briefing')
        self.set_theme_role(summarizer_box, 'panel')
        summarizer_layout = QVBoxLayout(summarizer_box)
        summarizer_layout.setContentsMargins(6, 10, 6, 6)
        summarizer_layout.setSpacing(6)
        self.p3_summary_text = QTextEdit()
        self.p3_summary_text.setReadOnly(True)
        self.p3_summary_text.setStyleSheet('font-size: 12px; padding: 6px;')
        self.p3_summary_text.setPlaceholderText(
            "The built-in news briefing refreshes automatically after news updates. "
            "Select a headline row to summarize one item, or press 'Generate Briefing' to rerun the full digest."
        )
        summarizer_layout.addWidget(self.p3_summary_text, 1)
        self.p3_summary_status = QLabel('')
        self.set_theme_role(self.p3_summary_status, 'status_muted')
        self.p3_summary_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summarizer_layout.addWidget(self.p3_summary_status)
        briefing_btns = QHBoxLayout()
        briefing_btns.setSpacing(6)
        summarize_all_btn = QPushButton('Generate Briefing')
        self.set_theme_variant(summarize_all_btn, 'accent')
        summarize_all_btn.clicked.connect(self._summarize_all_news)
        export_news_btn = QPushButton('Export News')
        self.set_theme_variant(export_news_btn, 'positive')
        export_news_btn.clicked.connect(self._p3_export_news)
        briefing_btns.addWidget(summarize_all_btn)
        briefing_btns.addWidget(export_news_btn)
        summarizer_layout.addLayout(briefing_btns)
        self._p3_summarizing = False
        panels_row.addWidget(summarizer_box, 1)
        layout.addLayout(panels_row, 1)

    def _apply_news_theme(self) -> None:
        """Refresh theme-dependent news page widgets."""
        if hasattr(self, 'p3_summary_status'):
            self.set_status_text(self.p3_summary_status, self.p3_summary_status.text(), status=self.p3_summary_status.property('bt_status') or 'muted')

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
        self._run_summarizer(articles, auto_trigger=False)

    def _p3_export_news(self) -> None:
        """Export all loaded news to clipboard as plain text."""
        portfolio_articles = self._p3_loaded_news.get('portfolio', [])
        macro_articles = self._p3_loaded_news.get('macro', [])
        if not portfolio_articles and not macro_articles:
            self.p3_summary_status.setText('No news to export.')
            return
        lines = []
        lines.append('=== NEWS EXPORT ===')
        lines.append('')
        if portfolio_articles:
            lines.append('--- PORTFOLIO NEWS ---')
            lines.append('')
            for a in self._sort_articles_by_newest(portfolio_articles):
                ticker = a.get('ticker', '')
                title = a.get('title', 'N/A')
                source = a.get('source', '')
                time_str = a.get('time', '')
                url = a.get('url', '')
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
        if macro_articles:
            lines.append('--- MARKET & MACRO NEWS ---')
            lines.append('')
            for a in self._sort_articles_by_newest(macro_articles):
                ticker = a.get('ticker', '')
                title = a.get('title', 'N/A')
                source = a.get('source', '')
                time_str = a.get('time', '')
                url = a.get('url', '')
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
        compare_presets = []
        if hasattr(self, 'p10_compare_presets'):
            compare_presets = list(getattr(self, 'p10_compare_presets', []))
        if not compare_presets:
            chart_page_state = load_chart_page_settings()
            compare_presets = list(chart_page_state.get('compare_presets', []))
        if compare_presets:
            lines.append('--- CHARTS COMPARE PRESETS ---')
            lines.append('')
            for preset in compare_presets:
                if not isinstance(preset, dict):
                    continue
                name = str(preset.get('name', '') or '').strip()
                symbols = list(preset.get('symbols', [])) if isinstance(preset.get('symbols', []), list) else []
                interval_label = str(preset.get('interval_label', '') or '').strip()
                range_label = str(preset.get('range_label', '') or '').strip()
                if not name:
                    continue
                lines.append(f'[{name}] {", ".join(symbols)}')
                meta = []
                if interval_label:
                    meta.append(f'Interval: {interval_label}')
                if range_label:
                    meta.append(f'Range: {range_label}')
                if meta:
                    lines.append('  ' + ' | '.join(meta))
                lines.append('')
        text = '\n'.join(lines)
        total = len(portfolio_articles) + len(macro_articles)
        QApplication.clipboard().setText(text)
        self.p3_summary_status.setText(
            f'Exported {total} articles to clipboard'
            + (f' with {len(compare_presets)} compare preset(s)' if compare_presets else '')
        )

    def _run_summarizer(self, articles: Any, auto_trigger: bool=False) -> None:
        """Handle run summarizer."""
        if self._p3_summarizing:
            self._p3_pending_summary_articles = [dict(article) for article in articles]
            self._p3_pending_summary_auto = bool(auto_trigger)
            return
        self._p3_pending_summary_articles = None
        self._p3_pending_summary_auto = False
        self._p3_summarizing = True
        if len(articles) == 1:
            label = articles[0]['title'][:55] + '...'
            body = (
                'Analyzing the selected headline with the built-in news rules...\n\n'
                'This summary uses headline wording, source, time, ticker, and category only.'
            )
            status_text = f'Analyzing selected headline: {label}'
        else:
            label = 'auto briefing refresh' if auto_trigger else 'full briefing'
            body = (
                'Analyzing loaded headlines with the built-in news briefing rules...\n\n'
                'The digest is deterministic and uses headline wording only.'
            )
            status_text = 'Refreshing full news briefing...' if auto_trigger else 'Generating full news briefing...'
        self.p3_summary_status.setText(status_text)
        self.p3_summary_text.setPlainText(body)
        self._summarizer_worker = NewsSummarizerWorker(articles)
        self._summarizer_worker.status.connect(self._on_summary_status)
        self._summarizer_worker.finished.connect(self._on_summary_ready)
        self._summarizer_worker.error.connect(self._on_summary_error)
        threading.Thread(target=self._summarizer_worker.run, daemon=True).start()

    def _on_summary_status(self, text: Any) -> None:
        """Reflect local-model download and generation progress in the UI."""
        self.p3_summary_status.setText(str(text or '').strip())

    def _on_summary_ready(self, text: Any) -> None:
        """Handle summary ready."""
        self._p3_summarizing = False
        self.p3_summary_text.setPlainText(text)
        self.p3_summary_status.setText('')
        self._run_pending_summary()

    def _on_summary_error(self, err: Any) -> None:
        """Handle summary error."""
        self._p3_summarizing = False
        self.p3_summary_text.setPlainText(f'Error: {err}')
        self.p3_summary_status.setText('News briefing failed.')
        self._run_pending_summary()

    def _run_pending_summary(self) -> None:
        """Run one queued summary request after the current one finishes."""
        if self._p3_summarizing or not self._p3_pending_summary_articles:
            return
        articles = list(self._p3_pending_summary_articles)
        auto_trigger = bool(self._p3_pending_summary_auto)
        self._p3_pending_summary_articles = None
        self._p3_pending_summary_auto = False
        self._run_summarizer(articles, auto_trigger=auto_trigger)

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
        if news:
            self._run_summarizer(news, auto_trigger=True)
        else:
            self._set_news_summary_idle_state(0)
