from __future__ import annotations

from typing import Any

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QAbstractItemView

from ..compat import *
from budget_terminal_app.services.chart_pattern_catalog import CHART_PATTERN_CATALOG
from budget_terminal_app.services.dictionary_catalog import (
    DICTIONARY_CATEGORIES,
    DICTIONARY_ENTRIES,
    DictionaryEntry,
    get_dictionary_entry,
    search_dictionary_entries,
)
from budget_terminal_app.widgets.chart_pattern_cheat_sheet import ChartPatternDiagramWidget


_CHART_PATTERN_BY_ID = {pattern.pattern_id: pattern for pattern in CHART_PATTERN_CATALOG}
_P38_NARROW_WIDTH = 820


class _DictionaryBody(QWidget):
    resized = Signal(int)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt virtual method
        super().resizeEvent(event)
        self.resized.emit(int(event.size().width()))


class DictionaryPageMixin:
    """Offline searchable stock-market learning reference."""

    def init_page38(self) -> None:
        layout = QVBoxLayout(self.page38)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Dictionary")
        self.set_theme_role(title, "page_title")
        subtitle = QLabel(
            "Stock-market, trading, investing, analysis, formula, chart-pattern, and economic-event reference"
        )
        subtitle.setWordWrap(True)
        self.set_theme_role(subtitle, "muted")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self.p38_status_label = QLabel(f"{len(DICTIONARY_ENTRIES)} entries · Offline reference")
        self.p38_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_theme_role(self.p38_status_label, "status_muted")
        header.addWidget(self.p38_status_label)
        layout.addLayout(header)

        self.p38_body = _DictionaryBody()
        body_layout = QVBoxLayout(self.p38_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.p38_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.p38_splitter.setChildrenCollapsible(False)
        body_layout.addWidget(self.p38_splitter)
        layout.addWidget(self.p38_body, 1)

        left_panel = QFrame()
        self.set_theme_role(left_panel, "panel")
        left_panel.setMinimumWidth(220)
        left_panel.setMaximumWidth(380)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)

        self.p38_search_input = QLineEdit()
        self.p38_search_input.setPlaceholderText("Search terms, aliases, formulas, or definitions...")
        self.p38_search_input.setClearButtonEnabled(True)
        self.p38_search_input.setAccessibleName("Search Dictionary")
        left_layout.addWidget(self.p38_search_input)

        self.p38_category_combo = QComboBox()
        self.p38_category_combo.setAccessibleName("Dictionary category")
        self.p38_category_combo.addItem("All categories")
        self.p38_category_combo.addItems(list(DICTIONARY_CATEGORIES))
        left_layout.addWidget(self.p38_category_combo)

        self.p38_result_count_label = QLabel()
        self.set_theme_role(self.p38_result_count_label, "muted")
        left_layout.addWidget(self.p38_result_count_label)

        self.p38_term_list = QListWidget()
        self.p38_term_list.setAccessibleName("Dictionary terms")
        self.p38_term_list.setAlternatingRowColors(True)
        self.p38_term_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.p38_term_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_layout.addWidget(self.p38_term_list, 1)

        self.p38_splitter.addWidget(left_panel)

        self.p38_detail_scroll = QScrollArea()
        self.p38_detail_scroll.setWidgetResizable(True)
        self.p38_detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.p38_detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.p38_detail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.p38_detail_host = QWidget()
        self.p38_detail_layout = QVBoxLayout(self.p38_detail_host)
        self.p38_detail_layout.setContentsMargins(14, 8, 14, 14)
        self.p38_detail_layout.setSpacing(10)
        self.p38_detail_scroll.setWidget(self.p38_detail_host)
        self.p38_splitter.addWidget(self.p38_detail_scroll)
        self.p38_splitter.setStretchFactor(0, 0)
        self.p38_splitter.setStretchFactor(1, 1)
        self.p38_splitter.setSizes([300, 760])

        self.p38_search_input.textChanged.connect(self._p38_apply_filters)
        self.p38_category_combo.currentTextChanged.connect(self._p38_apply_filters)
        self.p38_term_list.currentItemChanged.connect(self._p38_on_current_item_changed)
        self.p38_body.resized.connect(self._p38_update_responsive_layout)

        self.p38_visible_entries: tuple[DictionaryEntry, ...] = ()
        self.p38_selected_entry_id: str | None = None
        self.p38_pattern_diagram: ChartPatternDiagramWidget | None = None
        self.p38_detail_sections: list[tuple[str, str]] = []
        self._p38_apply_filters()
        self._p38_update_responsive_layout(self.p38_body.width())
        self._apply_dictionary_theme()

    def _p38_update_responsive_layout(self, width: Any) -> None:
        splitter = getattr(self, "p38_splitter", None)
        if splitter is None:
            return
        try:
            numeric_width = int(width)
        except (TypeError, ValueError):
            numeric_width = _P38_NARROW_WIDTH
        orientation = Qt.Orientation.Vertical if numeric_width < _P38_NARROW_WIDTH else Qt.Orientation.Horizontal
        if splitter.orientation() == orientation:
            return
        splitter.setOrientation(orientation)
        if orientation == Qt.Orientation.Vertical:
            splitter.setSizes([260, max(360, self.p38_body.height() - 260)])
        else:
            splitter.setSizes([300, max(520, numeric_width - 300)])

    def _p38_current_entry_id(self) -> str | None:
        item = getattr(self, "p38_term_list", None).currentItem() if hasattr(self, "p38_term_list") else None
        if item is None:
            return getattr(self, "p38_selected_entry_id", None)
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _p38_apply_filters(self, *_: Any, preferred_entry_id: str | None = None) -> None:
        if not hasattr(self, "p38_term_list"):
            return
        preserve_id = preferred_entry_id or self._p38_current_entry_id()
        query = self.p38_search_input.text()
        category = self.p38_category_combo.currentText()
        entries = search_dictionary_entries(query, category)
        self.p38_visible_entries = entries

        self.p38_term_list.blockSignals(True)
        self.p38_term_list.clear()
        selected_row = -1
        for row, entry in enumerate(entries):
            item = QListWidgetItem(entry.term)
            item.setData(Qt.ItemDataRole.UserRole, entry.entry_id)
            tooltip_parts = [entry.category]
            if entry.aliases:
                tooltip_parts.append("Also: " + ", ".join(entry.aliases))
            item.setToolTip("\n".join(tooltip_parts))
            self.p38_term_list.addItem(item)
            if preserve_id == entry.entry_id:
                selected_row = row
        if selected_row < 0 and entries:
            selected_row = 0
        if selected_row >= 0:
            self.p38_term_list.setCurrentRow(selected_row)
        self.p38_term_list.blockSignals(False)

        total = len(DICTIONARY_ENTRIES)
        shown = len(entries)
        self.p38_result_count_label.setText(f"{shown} of {total} terms")
        self.set_status_text(
            self.p38_status_label,
            f"Dictionary · {shown} of {total} terms · Offline reference",
            status="muted",
        )
        if selected_row >= 0:
            self._p38_render_entry(entries[selected_row])
        else:
            self._p38_render_empty(query=query, category=category)

    def _p38_on_current_item_changed(self, current: Any, _previous: Any) -> None:
        if current is None:
            self._p38_render_empty(
                query=self.p38_search_input.text(),
                category=self.p38_category_combo.currentText(),
            )
            return
        entry = get_dictionary_entry(str(current.data(Qt.ItemDataRole.UserRole) or ""))
        if entry is not None:
            self._p38_render_entry(entry)

    @staticmethod
    def _p38_clear_layout(layout: Any) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                DictionaryPageMixin._p38_clear_layout(child_layout)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _p38_add_text_block(self, title: str, body: str, *, formula: bool = False) -> QLabel:
        frame = QFrame()
        self.set_theme_role(frame, "panel")
        block_layout = QVBoxLayout(frame)
        block_layout.setContentsMargins(11, 9, 11, 10)
        block_layout.setSpacing(5)
        heading = QLabel(title)
        self.set_theme_role(heading, "section_title")
        block_layout.addWidget(heading)
        value = QLabel(body)
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.set_theme_role(value, "body")
        if formula:
            font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            value.setFont(font)
        block_layout.addWidget(value)
        self.p38_detail_layout.addWidget(frame)
        self.p38_detail_sections.append((title, body))
        return value

    def _p38_render_entry(self, entry: DictionaryEntry) -> None:
        self.p38_selected_entry_id = entry.entry_id
        self.p38_detail_sections = []
        self.p38_pattern_diagram = None
        self._p38_clear_layout(self.p38_detail_layout)

        top_row = QHBoxLayout()
        title = QLabel(entry.term)
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.set_theme_role(title, "page_title")
        self.p38_detail_title = title
        top_row.addWidget(title, 1)
        category_badge = QLabel(entry.category)
        category_badge.setObjectName("dictionaryCategoryBadge")
        category_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        category_badge.setWordWrap(True)
        top_row.addWidget(category_badge)
        self.p38_category_badge = category_badge
        self.p38_detail_layout.addLayout(top_row)

        if entry.aliases:
            alias_label = QLabel("Also known as: " + ", ".join(entry.aliases))
            alias_label.setWordWrap(True)
            alias_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.set_theme_role(alias_label, "muted")
            self.p38_detail_layout.addWidget(alias_label)

        pattern = _CHART_PATTERN_BY_ID.get(entry.chart_pattern_id or "")
        if pattern is not None:
            diagram = ChartPatternDiagramWidget(pattern)
            self.p38_pattern_diagram = diagram
            self.p38_detail_layout.addWidget(diagram)

        self._p38_add_text_block("Definition", entry.definition)
        self._p38_add_text_block("Why it matters", entry.why_it_matters)
        for section in entry.sections:
            self._p38_add_text_block(section.title, section.body, formula=section.title == "Formula")

        related_entries = [
            related
            for related_id in entry.related_entry_ids
            if (related := get_dictionary_entry(related_id)) is not None
        ]
        if related_entries:
            related_frame = QFrame()
            self.set_theme_role(related_frame, "panel")
            related_layout = QVBoxLayout(related_frame)
            related_layout.setContentsMargins(11, 9, 11, 10)
            related_layout.setSpacing(6)
            related_title = QLabel("Related terms")
            self.set_theme_role(related_title, "section_title")
            related_layout.addWidget(related_title)
            button_grid = QGridLayout()
            button_grid.setSpacing(6)
            for index, related in enumerate(related_entries):
                button = QPushButton(related.term)
                button.setToolTip(f"Open {related.term}")
                button.clicked.connect(lambda _checked=False, entry_id=related.entry_id: self._p38_open_related(entry_id))
                button_grid.addWidget(button, index // 2, index % 2)
            related_layout.addLayout(button_grid)
            self.p38_detail_layout.addWidget(related_frame)

        notice = QLabel("Educational reference only; definitions and examples are not investment advice.")
        notice.setWordWrap(True)
        self.set_theme_role(notice, "muted")
        self.p38_detail_layout.addWidget(notice)
        self.p38_detail_layout.addStretch(1)
        self.p38_detail_scroll.verticalScrollBar().setValue(0)
        self._apply_dictionary_theme()

    def _p38_render_empty(self, *, query: str, category: str) -> None:
        self.p38_selected_entry_id = None
        self.p38_pattern_diagram = None
        self.p38_detail_sections = []
        self._p38_clear_layout(self.p38_detail_layout)
        empty = QLabel("No matching Dictionary terms")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(empty, "page_title")
        detail = "Try a shorter search, an alias such as P/E or RSI, or another category."
        if not query and category == "All categories":
            detail = "The Dictionary catalog is unavailable."
        help_label = QLabel(detail)
        help_label.setWordWrap(True)
        help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_theme_role(help_label, "muted")
        self.p38_detail_layout.addStretch(1)
        self.p38_detail_layout.addWidget(empty)
        self.p38_detail_layout.addWidget(help_label)
        self.p38_detail_layout.addStretch(1)

    def _p38_open_related(self, entry_id: str) -> None:
        entry = get_dictionary_entry(entry_id)
        if entry is None:
            return
        # Clear filters when necessary so a related entry is always reachable.
        self.p38_search_input.blockSignals(True)
        self.p38_category_combo.blockSignals(True)
        self.p38_search_input.clear()
        self.p38_category_combo.setCurrentText("All categories")
        self.p38_search_input.blockSignals(False)
        self.p38_category_combo.blockSignals(False)
        self._p38_apply_filters(preferred_entry_id=entry.entry_id)

    def _p38_refresh_view(self) -> None:
        selected_id = self._p38_current_entry_id()
        self._p38_apply_filters(preferred_entry_id=selected_id)

    def _apply_dictionary_theme(self) -> None:
        if not hasattr(self, "p38_detail_scroll"):
            return
        self.p38_detail_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        badge = getattr(self, "p38_category_badge", None)
        if badge is not None:
            badge.setStyleSheet(
                f"color: {self.theme_color('accent')};"
                f"border: 1px solid {self.theme_color('accent')};"
                "border-radius: 9px; padding: 3px 8px; font-size: 10px; font-weight: bold;"
            )
        diagram = getattr(self, "p38_pattern_diagram", None)
        if diagram is not None:
            diagram.set_colors(
                {
                    "background": self.theme_color("chart_bg"),
                    "border": self.theme_color("panel_border"),
                    "grid": self.theme_color("chart_reference"),
                    "text": self.theme_color("text_muted"),
                    "bullish": self.theme_color("accent_positive"),
                    "bearish": self.theme_color("accent_negative"),
                    "neutral": self.theme_color("accent"),
                    "marker": self.theme_color("warning"),
                }
            )


__all__ = ["DictionaryPageMixin"]
