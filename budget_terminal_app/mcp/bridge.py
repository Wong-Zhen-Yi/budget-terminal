from __future__ import annotations

import base64
import datetime
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTableView,
    QTextEdit,
    QWidget,
)

from ..workers.data import DataWorker, NEWS_PAGE_REFRESH_REASON


class BridgeError(RuntimeError):
    """A safe, user-facing error raised by the Qt bridge."""


class BudgetTerminalBridge:
    """Expose the live Qt application through stable, serializable operations.

    Every method must run on the Qt main thread. The stdio server enforces that
    by dispatching incoming MCP requests through a Qt signal.
    """

    def __init__(self, window: Any) -> None:
        self.window = window
        self._control_sequence = 0

    def list_pages(self) -> dict[str, Any]:
        pages = []
        current = self._current_index()
        hidden = set()
        hidden_fn = getattr(self.window, "_hidden_navigation_pages", None)
        if callable(hidden_fn):
            hidden = set(hidden_fn())
        for index in self._registered_indexes():
            page = self.window._pages.get(index, {})
            button = page.get("btn") if isinstance(page, dict) else None
            label = self._page_label(index)
            pages.append(
                {
                    "index": index,
                    "name": label,
                    "visible_in_navigation": index not in hidden,
                    "initialized": self._page_initialized(index),
                    "current": index == current,
                    "enabled": bool(button is None or button.isEnabled()),
                }
            )
        return {"current_page": self._page_label(current), "current_index": current, "pages": pages}

    def status(self) -> dict[str, Any]:
        index = self._current_index()
        return {
            "application": QApplication.applicationDisplayName() or QApplication.applicationName() or "Budget Terminal",
            "window_title": str(self.window.windowTitle()),
            "current_page": self._page_label(index),
            "current_index": index,
            "page_initialized": self._page_initialized(index),
            "privacy_obscured": bool(getattr(self.window, "_privacy_obscured", False)),
            "refresh_busy": self._refresh_busy(),
            "window_visible": bool(self.window.isVisible()),
            "process_id": os.getpid(),
            "page_count": len(self._registered_indexes()),
        }

    def portfolio_tickers(self, portfolio: Any = "active") -> dict[str, Any]:
        """Return saved ticker symbols without depending on a rendered market-data table."""
        self._assert_page_readable(1)
        state = getattr(self.window, "all_portfolios_state", {})
        portfolios = state.get("portfolios", {}) if isinstance(state, dict) else {}
        if not isinstance(portfolios, dict):
            portfolios = {}
        requested = str(portfolio or "active").strip()
        requested_folded = requested.casefold()
        if requested_folded == "all":
            selected_ids = list(state.get("portfolio_order", [])) if isinstance(state, dict) else []
        elif requested_folded in {"active", "main"}:
            key = "active_portfolio_id" if requested_folded == "active" else "main_portfolio_id"
            selected_ids = [str(state.get(key) or getattr(self.window, key, ""))]
        elif requested in portfolios:
            selected_ids = [requested]
        else:
            selected_ids = [
                portfolio_id
                for portfolio_id, entry in portfolios.items()
                if isinstance(entry, dict) and str(entry.get("name", "")).casefold() == requested_folded
            ]
        selected_ids = [portfolio_id for portfolio_id in selected_ids if portfolio_id in portfolios]
        if not selected_ids:
            raise BridgeError(f"Portfolio not found: {portfolio!r}")
        results = []
        combined = []
        for portfolio_id in selected_ids:
            entry = portfolios.get(portfolio_id, {})
            tickers = []
            for value in entry.get("portfolio", []) if isinstance(entry, dict) else []:
                ticker = str(value or "").upper().strip()
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
                if ticker and ticker not in combined:
                    combined.append(ticker)
            results.append(
                {
                    "id": portfolio_id,
                    "name": str(entry.get("name") or portfolio_id),
                    "tickers": tickers,
                    "count": len(tickers),
                }
            )
        return {"portfolio": requested_folded, "tickers": combined, "count": len(combined), "portfolios": results}

    def portfolio_news(
        self,
        portfolio: Any = "active",
        *,
        max_articles: int = 50,
        max_per_ticker: int = 3,
    ) -> dict[str, Any]:
        """Fetch current ticker-specific news for a saved portfolio selection."""
        selection = self.portfolio_tickers(portfolio)
        tickers = list(selection.get("tickers", []))
        article_limit = max(1, min(int(max_articles), 100))
        ticker_limit = max(1, min(int(max_per_ticker), 10))
        cancelled = threading.Event()
        worker = DataWorker(
            tickers,
            [],
            cancel_check=cancelled.is_set,
            refresh_reason=NEWS_PAGE_REFRESH_REASON,
        )
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="BudgetTerminalMcpNews")
        future = executor.submit(worker.fetch_portfolio_news_only, ticker_limit)
        deadline = time.monotonic() + 45.0
        try:
            while not future.done() and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
            if not future.done():
                cancelled.set()
                raise BridgeError("Portfolio news fetch timed out after 45 seconds.")
            payload = future.result()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        articles = []
        raw_articles = list(payload.get("articles", []))
        for article in raw_articles[:article_limit]:
            try:
                timestamp = float(article.get("_ts") or 0)
            except (TypeError, ValueError):
                timestamp = 0.0
            published_at = (
                datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).isoformat()
                if timestamp > 0
                else None
            )
            articles.append(
                {
                    "ticker": str(article.get("ticker") or ""),
                    "title": str(article.get("title") or ""),
                    "publisher": str(article.get("source") or ""),
                    "url": str(article.get("url") or ""),
                    "published_at": published_at,
                }
            )
        return {
            "portfolio": selection.get("portfolio"),
            "portfolios": selection.get("portfolios", []),
            "queried_tickers": tickers,
            "articles": articles,
            "count": len(articles),
            "failed_tickers": list(payload.get("failed_tickers", [])),
            "truncated": len(raw_articles) > article_limit,
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def navigate(self, page: Any) -> dict[str, Any]:
        index = self._resolve_page(page)
        self.window.switch_page(index)
        QApplication.processEvents()
        return {
            "navigated": True,
            "index": self._current_index(),
            "page": self._page_label(self._current_index()),
            "initialized": self._page_initialized(index),
        }

    def refresh(self) -> dict[str, Any]:
        refresh = getattr(self.window, "_refresh_current_page", None)
        if not callable(refresh):
            raise BridgeError("The application does not expose page refresh behavior.")
        refresh()
        QApplication.processEvents()
        return {"refresh_requested": True, **self.status()}

    def set_privacy_mode(self, obscured: bool) -> dict[str, Any]:
        setter = getattr(self.window, "_set_pages_obscured", None)
        if not callable(setter):
            raise BridgeError("The application does not expose privacy controls.")
        setter(bool(obscured))
        QApplication.processEvents()
        return self.status()

    def wait_for_ui(self, timeout_ms: int = 1000, settle_ms: int = 100) -> dict[str, Any]:
        timeout_ms = max(0, min(int(timeout_ms), 30_000))
        settle_ms = max(0, min(int(settle_ms), timeout_ms))
        deadline = time.monotonic() + timeout_ms / 1000.0
        stable_since = None
        while time.monotonic() < deadline:
            QApplication.processEvents()
            busy = self._refresh_busy()
            if not busy:
                stable_since = stable_since or time.monotonic()
                if (time.monotonic() - stable_since) * 1000 >= settle_ms:
                    break
            else:
                stable_since = None
            time.sleep(0.01)
        return self.status()

    def _refresh_busy(self) -> bool:
        refresh = getattr(self.window, "top_refresh_btn", None)
        if refresh is not None and not refresh.isEnabled():
            return True
        if bool(getattr(self.window, "_p3_news_refresh_pending", False)):
            return True
        news_future = getattr(self.window, "_p3_news_refresh_future", None)
        return bool(news_future is not None and not news_future.done())

    def inspect_page(self, *, max_rows: int = 100, max_columns: int = 30) -> dict[str, Any]:
        index, page = self._current_page()
        self._assert_page_readable(index)
        max_rows = max(1, min(int(max_rows), 1000))
        max_columns = max(1, min(int(max_columns), 100))
        labels = []
        seen_labels = set()
        for label in page.findChildren(QLabel):
            if not label.isVisibleTo(page):
                continue
            text = self._clean_text(label.text())
            if text and text not in seen_labels:
                labels.append(text)
                seen_labels.add(text)

        controls = []
        tables = []
        lists = []
        text_blocks = []
        for widget in page.findChildren(QWidget):
            if not widget.isVisibleTo(page):
                continue
            if isinstance(widget, QTableView):
                tables.append(self._table_snapshot(widget, max_rows=max_rows, max_columns=max_columns))
            elif isinstance(widget, QListWidget):
                lists.append(self._list_snapshot(widget, max_rows=max_rows))
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                text = self._clean_text(widget.toPlainText())
                if text:
                    text_blocks.append({"id": self._control_id(widget), "text": text})
            if self._is_interactive(widget):
                controls.append(self._control_snapshot(widget))
        return {
            "page": self._page_label(index),
            "index": index,
            "labels": labels,
            "controls": controls,
            "tables": tables,
            "lists": lists,
            "text_blocks": text_blocks,
            "limits": {"max_rows": max_rows, "max_columns": max_columns},
        }

    def export_page(self, *, format: str = "markdown", max_rows: int = 100, max_columns: int = 30) -> str:
        snapshot = self.inspect_page(max_rows=max_rows, max_columns=max_columns)
        if str(format).lower() == "json":
            return json.dumps(snapshot, indent=2, ensure_ascii=False)
        if str(format).lower() != "markdown":
            raise BridgeError("format must be 'markdown' or 'json'.")
        lines = [f"# Budget Terminal — {snapshot['page']}", ""]
        if snapshot["labels"]:
            lines.extend(["## Visible text", "", *[f"- {value}" for value in snapshot["labels"]], ""])
        for table in snapshot["tables"]:
            lines.extend([f"## {table['name']}", ""])
            headers = table["headers"] or [f"Column {i + 1}" for i in range(table["column_count"])]
            lines.append("| " + " | ".join(self._markdown_cell(value) for value in headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in table["rows"]:
                lines.append("| " + " | ".join(self._markdown_cell(value) for value in row) + " |")
            if table["truncated"]:
                lines.extend(["", f"_Truncated: showing {len(table['rows'])} of {table['row_count']} rows._"])
            lines.append("")
        for block in snapshot["text_blocks"]:
            lines.extend(["## Text", "", block["text"], ""])
        if snapshot["lists"]:
            lines.extend(["## Lists", ""])
            for item_list in snapshot["lists"]:
                lines.append(f"### {item_list['name']}")
                lines.extend(f"- {item}" for item in item_list["items"])
                lines.append("")
        if snapshot["controls"]:
            lines.extend(["## Current controls", ""])
            for control in snapshot["controls"]:
                value = control.get("value")
                suffix = f": {value}" if value not in (None, "") else ""
                lines.append(f"- {control['type']} `{control['id']}` — {control['name']}{suffix}")
        return "\n".join(lines).strip()

    def interact(self, control_id: str, action: str, value: Any = None, row: Any = None, column: Any = None) -> dict[str, Any]:
        _, page = self._current_page()
        widget = self._find_control(page, control_id)
        if not widget.isEnabled():
            raise BridgeError(f"Control is currently disabled: {control_id!r}.")
        action = str(action or "").strip().lower()
        if action == "click" and isinstance(widget, QAbstractButton):
            widget.click()
        elif action == "set_text" and isinstance(widget, QLineEdit):
            widget.setText(str(value or ""))
        elif action == "set_text" and isinstance(widget, (QTextEdit, QPlainTextEdit)):
            widget.setPlainText(str(value or ""))
        elif action == "select" and isinstance(widget, QComboBox):
            if isinstance(value, int):
                target = value
            else:
                target = widget.findText(str(value))
            if target < 0 or target >= widget.count():
                raise BridgeError(f"Combo-box option not found: {value!r}")
            widget.setCurrentIndex(target)
        elif action == "select" and isinstance(widget, QTabWidget):
            target = int(value) if isinstance(value, int) else next(
                (i for i in range(widget.count()) if widget.tabText(i).casefold() == str(value).casefold()), -1
            )
            if target < 0 or target >= widget.count():
                raise BridgeError(f"Tab not found: {value!r}")
            widget.setCurrentIndex(target)
        elif action == "select" and isinstance(widget, QListWidget):
            if isinstance(value, int):
                target = value
            else:
                target = next(
                    (i for i in range(widget.count()) if widget.item(i).text().casefold() == str(value).casefold()),
                    -1,
                )
            if target < 0 or target >= widget.count():
                raise BridgeError(f"List option not found: {value!r}")
            widget.setCurrentRow(target)
            widget.itemClicked.emit(widget.item(target))
        elif action == "set_value" and isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(float(value) if isinstance(widget, QDoubleSpinBox) else int(value))
        elif action == "set_value" and isinstance(widget, QSlider):
            widget.setValue(int(value))
        elif action == "check" and isinstance(widget, QAbstractButton) and widget.isCheckable():
            widget.setChecked(bool(value))
        elif action == "activate_cell" and isinstance(widget, QTableView):
            model = widget.model()
            model_index = model.index(int(row), int(column))
            if not model_index.isValid():
                raise BridgeError("The requested table cell is outside the model.")
            widget.setCurrentIndex(model_index)
            widget.activated.emit(model_index)
        else:
            raise BridgeError(f"Action {action!r} is not supported by {type(widget).__name__}.")
        QApplication.processEvents()
        return {"interaction_completed": True, "control": self._control_snapshot(widget)}

    def capture_page(self) -> str:
        index, page = self._current_page()
        self._assert_page_readable(index)
        pixmap = page.grab()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not pixmap.save(buffer, "PNG"):
            raise BridgeError("Could not capture the current page.")
        return base64.b64encode(bytes(buffer.data())).decode("ascii")

    def _registered_indexes(self) -> list[int]:
        indexes = list(getattr(self.window, "_pages", {}).keys())
        order_fn = getattr(self.window, "_navigation_page_order", None)
        if callable(order_fn):
            ordered = [int(value) for value in order_fn() if int(value) in indexes]
            ordered.extend(index for index in indexes if index not in ordered)
            return ordered
        return sorted(int(value) for value in indexes)

    def _resolve_page(self, page: Any) -> int:
        indexes = self._registered_indexes()
        try:
            numeric = int(page)
        except (TypeError, ValueError):
            numeric = None
        if numeric in indexes:
            return int(numeric)
        requested = str(page or "").strip().casefold()
        matches = [index for index in indexes if self._page_label(index).casefold() == requested]
        if len(matches) == 1:
            return matches[0]
        available = ", ".join(self._page_label(index) for index in indexes)
        raise BridgeError(f"Unknown page {page!r}. Available pages: {available}")

    def _current_index(self) -> int:
        return int(self.window.stacked_widget.currentIndex())

    def _current_page(self) -> tuple[int, QWidget]:
        index = self._current_index()
        page = self.window.stacked_widget.currentWidget()
        if not isinstance(page, QWidget):
            raise BridgeError("The current application page is unavailable.")
        return index, page

    def _page_label(self, index: int) -> str:
        label_fn = getattr(self.window, "_page_label", None)
        return str(label_fn(index) if callable(label_fn) else f"Page {index}")

    def _page_initialized(self, index: int) -> bool:
        initialized_fn = getattr(self.window, "_page_initialized", None)
        return bool(initialized_fn(index=index)) if callable(initialized_fn) else True

    def _assert_page_readable(self, index: int) -> None:
        targets_fn = getattr(self.window, "_privacy_target_page_indexes", None)
        targets = set(targets_fn()) if callable(targets_fn) else set()
        if bool(getattr(self.window, "_privacy_obscured", False)) and index in targets:
            raise BridgeError("This page is obscured by the application's privacy mode. Reveal it before exporting data.")

    def _control_id(self, widget: QWidget) -> str:
        existing = str(widget.property("bt_mcp_id") or "")
        if existing:
            return existing
        object_name = str(widget.objectName() or "").strip()
        if object_name:
            candidate = object_name
        else:
            self._control_sequence += 1
            candidate = f"{type(widget).__name__}-{self._control_sequence}"
        widget.setProperty("bt_mcp_id", candidate)
        return candidate

    def _find_control(self, page: QWidget, control_id: str) -> QWidget:
        for widget in [page, *page.findChildren(QWidget)]:
            if str(widget.property("bt_mcp_id") or "") == str(control_id):
                return widget
        raise BridgeError(f"Control not found on the current page: {control_id!r}. Inspect the page again to get current IDs.")

    @staticmethod
    def _is_interactive(widget: QWidget) -> bool:
        return isinstance(
            widget,
            (
                QAbstractButton,
                QLineEdit,
                QTextEdit,
                QPlainTextEdit,
                QComboBox,
                QAbstractSpinBox,
                QSlider,
                QTabWidget,
                QListWidget,
            ),
        )

    def _control_snapshot(self, widget: QWidget) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self._control_id(widget),
            "type": type(widget).__name__,
            "name": self._widget_name(widget),
            "enabled": widget.isEnabled(),
        }
        if isinstance(widget, QAbstractButton):
            result["value"] = bool(widget.isChecked()) if widget.isCheckable() else None
            result["actions"] = ["click", "check"] if widget.isCheckable() else ["click"]
        elif isinstance(widget, QLineEdit):
            result["value"] = (
                self._clean_text(widget.text())
                if widget.echoMode() == QLineEdit.EchoMode.Normal
                else "[redacted]"
            )
            result["placeholder"] = self._clean_text(widget.placeholderText())
            result["actions"] = ["set_text"]
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            text = self._clean_text(widget.toPlainText())
            result["value"] = text if len(text) <= 240 else f"{text[:237]}..."
            result["text_length"] = len(text)
            result["actions"] = ["set_text"]
        elif isinstance(widget, QComboBox):
            result["value"] = self._clean_text(widget.currentText())
            result["options"] = [self._clean_text(widget.itemText(i)) for i in range(widget.count())]
            result["actions"] = ["select"]
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            result["value"] = widget.value()
            result["actions"] = ["set_value"]
        elif isinstance(widget, QSlider):
            result["value"] = widget.value()
            result["minimum"] = widget.minimum()
            result["maximum"] = widget.maximum()
            result["actions"] = ["set_value"]
        elif isinstance(widget, QTabWidget):
            result["value"] = self._clean_text(widget.tabText(widget.currentIndex())) if widget.currentIndex() >= 0 else ""
            result["options"] = [self._clean_text(widget.tabText(i)) for i in range(widget.count())]
            result["actions"] = ["select"]
        elif isinstance(widget, QListWidget):
            result["value"] = self._clean_text(widget.currentItem().text()) if widget.currentItem() else ""
            result["actions"] = ["select"]
        return result

    def _table_snapshot(self, table: QTableView, *, max_rows: int, max_columns: int) -> dict[str, Any]:
        model = table.model()
        row_count = int(model.rowCount()) if model is not None else 0
        column_count = int(model.columnCount()) if model is not None else 0
        shown_columns = min(column_count, max_columns)
        headers = [
            self._clean_text(model.headerData(column, Qt.Orientation.Horizontal))
            for column in range(shown_columns)
        ] if model else []
        rows = []
        if model:
            for row in range(min(row_count, max_rows)):
                rows.append([self._clean_text(model.data(model.index(row, column))) for column in range(shown_columns)])
        return {
            "id": self._control_id(table),
            "name": self._widget_name(table, fallback="Table"),
            "row_count": row_count,
            "column_count": column_count,
            "headers": headers,
            "rows": rows,
            "truncated": row_count > max_rows or column_count > max_columns,
            "actions": ["activate_cell"],
        }

    def _list_snapshot(self, widget: QListWidget, *, max_rows: int) -> dict[str, Any]:
        return {
            "id": self._control_id(widget),
            "name": self._widget_name(widget, fallback="List"),
            "item_count": widget.count(),
            "items": [self._clean_text(widget.item(i).text()) for i in range(min(widget.count(), max_rows))],
            "truncated": widget.count() > max_rows,
        }

    def _widget_name(self, widget: QWidget, *, fallback: str = "control") -> str:
        for value in (
            widget.accessibleName(),
            widget.toolTip(),
            widget.text() if isinstance(widget, QAbstractButton) else "",
            widget.placeholderText() if isinstance(widget, QLineEdit) else "",
            widget.objectName(),
        ):
            clean = self._clean_text(value)
            if clean:
                return clean
        return fallback

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").replace("\x00", "").split())

    @staticmethod
    def _markdown_cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ")
