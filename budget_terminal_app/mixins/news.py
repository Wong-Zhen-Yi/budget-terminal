from __future__ import annotations

import time
from html import escape
from typing import Any

from ..compat import *
from ..workers.data import DataWorker, NEWS_PAGE_REFRESH_REASON
from ..workers.news_preview import build_news_preview_text


class _NewsPreviewSignals(QObject):
    preview_ready = pyqtSignal(int, object, object)


class NewsMixin:

    def _sort_articles_by_newest(self, articles: Any) -> Any:
        """Return newest articles first."""
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
        """Factory: create a standard 4-column news QTableWidget."""
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

    def init_page3(self) -> None:
        """Build the News page UI."""
        self._p3_loaded_news = {'portfolio': [], 'macro': [], 'other': []}
        self._p3_highlighted_news: dict[str, Any] | None = None
        self._p3_preview_request_id = 0
        self._p3_news_refresh_request_id = 0
        self._p3_news_refresh_pending = False
        self._p3_syncing_news_selection = False
        self._p3_preview_signals = _NewsPreviewSignals()
        self._p3_preview_signals.preview_ready.connect(self._p3_on_preview_ready)

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
        self.p3_portfolio_table = self._make_news_table(
            self._p3_highlight_news_from_table,
            self._open_news_link_table,
            self._p3_highlight_current_news_from_table,
            show_full_headlines=True,
            time_header='Age',
            show_age=True,
        )
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
        self.p3_macro_table = self._make_news_table(
            self._p3_highlight_news_from_table,
            self._open_news_link_table,
            self._p3_highlight_current_news_from_table,
            show_full_headlines=True,
            time_header='Age',
            show_age=True,
        )
        macro_layout.addWidget(self.p3_macro_table, 1)
        self.p3_export_macro_news_btn = QPushButton('Export Market && Macro News')
        self.set_theme_variant(self.p3_export_macro_news_btn, 'positive')
        self.p3_export_macro_news_btn.clicked.connect(self._p3_export_macro_news)
        macro_layout.addWidget(self.p3_export_macro_news_btn)
        panels_row.addWidget(macro_box, 1)

        preview_box = QGroupBox('News Preview')
        self.set_theme_role(preview_box, 'panel')
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(10, 12, 10, 8)
        preview_layout.setSpacing(8)

        self.p3_preview_title_lbl = QLabel('Select a news item to preview')
        self.p3_preview_title_lbl.setWordWrap(True)
        self.p3_preview_title_lbl.setTextFormat(Qt.TextFormat.RichText)
        preview_layout.addWidget(self.p3_preview_title_lbl)

        self.p3_preview_meta_lbl = QLabel('Ticker: -- | Source: -- | Age: --')
        self.p3_preview_meta_lbl.setWordWrap(True)
        preview_layout.addWidget(self.p3_preview_meta_lbl)

        self.p3_preview_url_lbl = QLabel('URL: --')
        self.p3_preview_url_lbl.setWordWrap(True)
        self.p3_preview_url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_layout.addWidget(self.p3_preview_url_lbl)

        self.p3_preview_body = QPlainTextEdit()
        self.p3_preview_body.setReadOnly(True)
        self.p3_preview_body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.p3_preview_body.setPlainText('Select a headline to load a readable article preview.')
        preview_layout.addWidget(self.p3_preview_body, 1)

        self.p3_open_external_btn = QPushButton('Open Externally')
        self.p3_open_external_btn.setEnabled(False)
        self.set_theme_variant(self.p3_open_external_btn, 'positive')
        self.p3_open_external_btn.clicked.connect(self._p3_open_highlighted_news_external)
        preview_layout.addWidget(self.p3_open_external_btn)
        panels_row.addWidget(preview_box, 1)

        layout.addLayout(panels_row, 1)

    def _apply_news_theme(self) -> None:
        """Refresh theme-dependent news page widgets."""
        return

    def _p3_set_status(self, text: str, status: str) -> None:
        """Mirror News page status updates into the shared footer."""
        if hasattr(self, 'status_bar'):
            self.set_status_text(self.status_bar, text, status=status)

    def _p3_article_age_text(self, article: Any) -> str:
        """Return a compact relative age label for one News page article."""
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
        """Open the clicked news article."""
        row = item.row()
        headline_item = table.item(row, 0)
        if headline_item:
            url = headline_item.data(Qt.ItemDataRole.UserRole)
            if url:
                logger.info('Opening news link: %s', url)
                webbrowser.open(url)

    def _p3_get_article_from_table_item(self, item: Any, table: Any) -> dict[str, Any] | None:
        """Return the article payload stored on a news table row."""
        row = item.row()
        headline_item = table.item(row, 0)
        if not headline_item:
            return None
        article = headline_item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(article, dict):
            return dict(article)
        return None

    def _p3_highlight_news_from_table(self, item: Any, table: Any) -> None:
        """Make a single table article the active News Preview article."""
        article = self._p3_get_article_from_table_item(item, table)
        self._p3_highlight_news_article(article, table)

    def _p3_highlight_current_news_from_table(self, table: Any) -> None:
        """Refresh News Preview when keyboard navigation changes table selection."""
        if getattr(self, '_p3_syncing_news_selection', False):
            return
        current_item = table.currentItem()
        if current_item is None:
            return
        article = self._p3_get_article_from_table_item(current_item, table)
        self._p3_highlight_news_article(article, table)

    def _p3_highlight_news_article(self, article: dict[str, Any] | None, table: Any) -> None:
        """Apply one highlighted article and keep other news tables visually unselected."""
        if not article:
            return
        for other_table in (getattr(self, 'p3_portfolio_table', None), getattr(self, 'p3_macro_table', None)):
            if other_table is not None and other_table is not table:
                self._p3_syncing_news_selection = True
                try:
                    other_table.clearSelection()
                    other_table.setCurrentCell(-1, -1)
                finally:
                    self._p3_syncing_news_selection = False
        self._p3_set_highlighted_news(article)

    def _p3_set_highlighted_news(self, article: dict[str, Any] | None) -> None:
        """Store and render the one highlighted News page article."""
        current = getattr(self, '_p3_highlighted_news', None)
        if article and current and self._p3_article_key(article) == self._p3_article_key(current):
            return
        self._p3_highlighted_news = dict(article) if isinstance(article, dict) else None
        self._p3_render_news_preview()

    def _p3_render_news_preview(self) -> None:
        """Render the selected article in the News Preview panel."""
        article = getattr(self, '_p3_highlighted_news', None)
        has_article = isinstance(article, dict) and bool(article)
        if not has_article:
            self._p3_preview_request_id += 1
            self.p3_preview_title_lbl.setText('Select a news item to preview')
            self.p3_preview_meta_lbl.setText('Ticker: -- | Source: -- | Age: --')
            self.p3_preview_url_lbl.setText('URL: --')
            self.p3_preview_body.setPlainText('Select a headline to load a readable article preview.')
            self.p3_open_external_btn.setEnabled(False)
            return

        title = escape(str(article.get('title') or 'N/A'))
        ticker = str(article.get('ticker') or '--')
        source = str(article.get('source') or '--')
        age_str = self._p3_article_age_text(article)
        url = str(article.get('url') or '')
        self.p3_preview_title_lbl.setText(f'<b>{title}</b>')
        self.p3_preview_meta_lbl.setText(f'Ticker: {ticker} | Source: {source} | Age: {age_str}')
        self.p3_preview_url_lbl.setText(f'URL: {url or "--"}')
        self.p3_preview_body.setPlainText('Loading readable preview...')
        self.p3_open_external_btn.setEnabled(bool(url))
        self._p3_fetch_news_preview(dict(article))

    def _p3_fetch_news_preview(self, article: dict[str, Any]) -> None:
        """Fetch the readable article preview outside the UI thread."""
        self._p3_preview_request_id += 1
        request_id = self._p3_preview_request_id
        article_key = self._p3_article_key(article)

        def _run() -> None:
            result = build_news_preview_text(article)
            self._p3_preview_signals.preview_ready.emit(request_id, article_key, result)

        threading.Thread(target=_run, daemon=True).start()

    def _p3_on_preview_ready(self, request_id: int, article_key: object, result: object) -> None:
        """Apply a readable preview result if it still matches the selection."""
        if request_id != getattr(self, '_p3_preview_request_id', 0):
            return
        highlighted = getattr(self, '_p3_highlighted_news', None)
        if self._p3_article_key(highlighted) != article_key:
            return
        payload = result if isinstance(result, dict) else {}
        text = str(payload.get('text') or '').strip()
        error = str(payload.get('error') or '').strip()
        self.p3_preview_body.setPlainText(text or 'Preview unavailable. Open externally for the full article.')
        if error:
            logger.info('News preview unavailable: %s', error)
            self._p3_set_status('Preview unavailable. Open externally for the full article.', 'warning')
            if hasattr(self, 'status_bar'):
                self.status_bar.setToolTip(error)

    def _p3_open_highlighted_news_external(self) -> None:
        """Open the highlighted News Preview article externally."""
        article = getattr(self, '_p3_highlighted_news', None)
        url = str(article.get('url') or '') if isinstance(article, dict) else ''
        if not url:
            self._p3_set_status('No highlighted news URL to open.', 'warning')
            return
        logger.info('Opening highlighted news link: %s', url)
        webbrowser.open(url)

    def _p3_article_key(self, article: Any) -> tuple[str, ...]:
        """Return a stable-enough key for preserving a highlighted news item."""
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

    def _p3_select_news_table_row(self, table: Any, row: int, focus: bool = False) -> None:
        """Select one News table row and optionally keep keyboard navigation there."""
        if table is None or row < 0 or row >= table.rowCount():
            return
        table.setCurrentCell(row, 0)
        table.selectRow(row)
        if focus:
            table.setFocus(Qt.FocusReason.OtherFocusReason)
        self._p3_highlight_current_news_from_table(table)

    def _p3_select_highlighted_news_row(self) -> None:
        """Restore the visual row selection for the currently highlighted article."""
        highlighted_key = self._p3_article_key(getattr(self, '_p3_highlighted_news', None))
        if highlighted_key == ('',):
            return
        for table in (getattr(self, 'p3_portfolio_table', None), getattr(self, 'p3_macro_table', None)):
            if table is None:
                continue
            for row in range(table.rowCount()):
                article = self._p3_get_article_from_table_item(table.item(row, 0), table)
                if self._p3_article_key(article) == highlighted_key:
                    self._p3_select_news_table_row(table, row)
                    return

    def _p3_preserve_highlighted_news(self, articles: list[dict[str, Any]]) -> bool:
        """Keep the current preview article after refresh if it still exists."""
        highlighted = getattr(self, '_p3_highlighted_news', None)
        if not highlighted:
            self._p3_set_highlighted_news(None)
            return False
        highlighted_key = self._p3_article_key(highlighted)
        for article in articles:
            if self._p3_article_key(article) == highlighted_key:
                self._p3_set_highlighted_news(article)
                self._p3_select_highlighted_news_row()
                return True
        self._p3_set_highlighted_news(None)
        return False

    def _p3_select_first_portfolio_news(self) -> None:
        """Select the first portfolio headline so startup has a live preview."""
        table = getattr(self, 'p3_portfolio_table', None)
        if table is None or table.rowCount() <= 0:
            return
        self._p3_select_news_table_row(table, 0, focus=True)

    def _p3_build_export_text(self, heading: str, articles: list[dict[str, Any]]) -> str:
        """Build plain-text clipboard export content for one news section."""
        lines = [f'=== {heading.upper()} ===', '']
        for article in self._sort_articles_by_newest(articles):
            ticker = article.get('ticker', '')
            title = article.get('title', 'N/A')
            source = article.get('source', '')
            age_str = self._p3_article_age_text(article)
            url = article.get('url', '')
            lines.append(f'[{ticker}] {title}')
            meta = []
            if source:
                meta.append(f'Source: {source}')
            meta.append(f'Age: {age_str}')
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

    def _populate_news_table(self, table: Any, articles: Any) -> None:
        """Populate one of the News page tables."""
        table.setRowCount(0)
        for article in self._sort_articles_for_news_table(articles):
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

            time_text = self._p3_article_age_text(article) if table.property('bt_show_age') else article.get('time', '')
            time_item = QTableWidgetItem(time_text)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 3, time_item)
        if table.property('bt_full_headlines'):
            self._p3_fit_full_headline_rows(table)
        table.clearSelection()
        table.setCurrentCell(-1, -1)
        table.scrollToTop()

    def _p3_fit_full_headline_rows(self, table: Any) -> None:
        """Resize News page rows so wrapped headlines are readable."""
        table.resizeRowsToContents()
        min_height = 54
        max_height_property = table.property('bt_full_headlines_max_height')
        max_height = 112 if max_height_property is None else int(max_height_property)
        for row in range(table.rowCount()):
            height = max(min_height, table.rowHeight(row))
            if max_height > 0:
                height = min(max_height, height)
            table.setRowHeight(row, height)

    def _p3_fetch_tickers(self) -> list[str]:
        """Return the current portfolio universe for a News-only refresh."""
        get_fetch_tickers = getattr(self, '_get_fetch_tickers', None)
        if callable(get_fetch_tickers):
            return list(get_fetch_tickers())
        return list(getattr(self, 'tickers', []) or [])

    def _p3_emit_main(self, fn: Any) -> None:
        """Run one callback on the main thread when the app signal is available."""
        signal = getattr(self, '_invoke_main', None)
        if signal is not None and hasattr(signal, 'emit'):
            signal.emit(fn)
        else:
            fn()

    def _p3_request_news_refresh(self) -> None:
        """Refresh the News page without reloading Dashboard chart/options data."""
        self._p3_news_refresh_request_id = int(getattr(self, '_p3_news_refresh_request_id', 0) or 0) + 1
        request_id = self._p3_news_refresh_request_id
        tickers = self._p3_fetch_tickers()
        self._p3_news_refresh_pending = True
        self._p3_set_status('Refreshing news...', 'info')
        executor_factory = getattr(self, '_ensure_dashboard_fetch_executor', None)
        if not callable(executor_factory):
            self._p3_handle_news_refresh_error(request_id, 'News refresh executor is unavailable.')
            return
        self._p3_news_refresh_future = executor_factory().submit(self._p3_run_news_refresh, request_id, tickers)

    def _p3_run_news_refresh(self, request_id: int, tickers: list[str]) -> None:
        """Run a News-only worker and hand the result back to the UI thread."""
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
                    cancel_check=lambda req=request_id: req != getattr(self, '_p3_news_refresh_request_id', 0),
                    cache_manager=cache_manager_factory() if callable(cache_manager_factory) else None,
                    refresh_reason=NEWS_PAGE_REFRESH_REASON,
                    allow_non_chart_reuse=False,
                )
                data = worker.fetch()
            if data is not None:
                self._p3_emit_main(lambda payload=data, req=request_id: self._p3_apply_news_refresh_result(req, payload))
            else:
                self._p3_emit_main(lambda req=request_id: self._p3_handle_news_refresh_error(req, 'News worker returned no data.'))
        except Exception as exc:
            logger.error('News refresh failed: %s', exc)
            self._p3_emit_main(lambda msg=str(exc), req=request_id: self._p3_handle_news_refresh_error(req, msg))

    def _p3_merge_news_refresh_data(self, data: Any) -> list[dict[str, Any]]:
        """Replace only the loaded news slice while preserving existing dashboard data."""
        news = [dict(article) for article in (data.get('news', []) if isinstance(data, dict) else [])]
        current = getattr(self, 'last_data', None)
        if isinstance(current, dict):
            merged = dict(current)
            merged['news'] = [dict(article) for article in news]
            self.last_data = merged
        elif isinstance(data, dict):
            self.last_data = dict(data)
        return news

    def _p3_apply_news_refresh_result(self, request_id: int, data: Any) -> None:
        """Apply a News-only refresh if it is still the newest request."""
        if request_id != int(getattr(self, '_p3_news_refresh_request_id', 0) or 0):
            return
        self._p3_news_refresh_pending = False
        news = self._p3_merge_news_refresh_data(data)
        logger.info('Applying News page refresh %s with %s article(s).', request_id, len(news))
        self.update_page3({'news': news})
        status = 'positive' if news else 'warning'
        self._p3_set_status(f'News refreshed: {len(news)} article(s).', status)

    def _p3_handle_news_refresh_error(self, request_id: int, message: Any) -> None:
        """Show a News refresh failure unless a newer refresh superseded it."""
        if request_id != int(getattr(self, '_p3_news_refresh_request_id', 0) or 0):
            return
        self._p3_news_refresh_pending = False
        text = str(message or 'Unknown error')
        self._p3_set_status(f'News refresh failed: {text}', 'negative')

    def update_page3(self, data: Any) -> None:
        """Update the News page tables."""
        news = data.get('news', [])
        portfolio_news = self._sort_articles_by_newest([article for article in news if article.get('category') == 'portfolio'])
        macro_news = self._sort_articles_by_newest([article for article in news if article.get('category') == 'macro'])
        all_news = self._sort_articles_for_news_table([article for article in news if article.get('category') == 'other'])
        self._p3_loaded_news = {
            'portfolio': [dict(article) for article in portfolio_news],
            'macro': [dict(article) for article in macro_news],
            'other': [dict(article) for article in all_news],
        }
        self._populate_news_table(self.p3_portfolio_table, portfolio_news)
        self._populate_news_table(self.p3_macro_table, macro_news)
        preserved = self._p3_preserve_highlighted_news(self._p3_loaded_news['portfolio'] + self._p3_loaded_news['macro'])
        if not preserved and not getattr(self, '_p3_highlighted_news', None):
            self._p3_select_first_portfolio_news()
