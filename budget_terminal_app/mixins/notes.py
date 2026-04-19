from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QPixmap, QTextCursor
from PyQt6.QtWidgets import QListView

from ..compat import *
from budget_terminal_app.paths import user_data_dir


class NotesMixin:
    _P17_SAVE_DEBOUNCE_MS = 450
    _P17_IMAGE_FILTER = 'Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)'

    def init_page17(self) -> None:
        self._p17_loading_note = False
        self._p17_internal_note_select = False
        self._p17_selected_note_id: str | None = None
        self._p17_selected_image_id: str | None = None
        self._p17_note_dirty = False
        self._p17_first_visit_blank_pending = False
        self._p17_startup_blank_mode = False
        self._p17_startup_draft_note_id: str | None = None
        self._p17_notes_save_timer = QTimer(self)
        self._p17_notes_save_timer.setSingleShot(True)
        self._p17_notes_save_timer.timeout.connect(self._p17_save_selected_note)
        if not hasattr(self, 'notes_data'):
            self.notes_data = load_notes_data()
        self._p17_first_visit_blank_pending = bool(self.notes_data)
        self._p17_startup_blank_mode = bool(self.notes_data)

        layout = QVBoxLayout(self.page17)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_lbl = QLabel('<b>Notes</b>')
        self.set_theme_role(title_lbl, 'page_title')
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        self.p17_new_btn = QPushButton('New Note')
        self.set_theme_variant(self.p17_new_btn, 'accent')
        self.p17_new_btn.clicked.connect(self._p17_create_note)
        self.p17_delete_btn = QPushButton('Delete Note')
        self.p17_delete_btn.clicked.connect(self._p17_delete_selected_note)
        title_row.addWidget(self.p17_new_btn)
        title_row.addWidget(self.p17_delete_btn)
        layout.addLayout(title_row)

        intro_lbl = QLabel('Notes are sorted newest first, track created and edited timestamps automatically, and can include attached pictures.')
        intro_lbl.setWordWrap(True)
        self.set_theme_role(intro_lbl, 'muted')
        layout.addWidget(intro_lbl)

        self.p17_status_lbl = QLabel('Ready')
        self.set_theme_role(self.p17_status_lbl, 'status_muted')
        layout.addWidget(self.p17_status_lbl)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(content_splitter, 1)

        left_panel = QFrame()
        self.set_theme_role(left_panel, 'panel')
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        notes_label = QLabel('All Notes')
        self.set_theme_role(notes_label, 'section_title')
        left_layout.addWidget(notes_label)

        self.p17_note_list = QListWidget()
        self.p17_note_list.currentItemChanged.connect(self._p17_on_note_selection_changed)
        left_layout.addWidget(self.p17_note_list, 1)
        content_splitter.addWidget(left_panel)

        editor_panel = QFrame()
        self.set_theme_role(editor_panel, 'panel')
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        editor_layout.setSpacing(8)

        title_label = QLabel('Title')
        self.set_theme_role(title_label, 'section_title')
        editor_layout.addWidget(title_label)
        self.p17_title_edit = QLineEdit()
        self.p17_title_edit.setPlaceholderText('Type a title to create a note')
        self.p17_title_edit.textChanged.connect(self._p17_on_note_fields_changed)
        editor_layout.addWidget(self.p17_title_edit)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        category_label = QLabel('Category')
        self.set_theme_role(category_label, 'section_title')
        meta_row.addWidget(category_label)
        self.p17_category_combo = QComboBox()
        self.p17_category_combo.addItems(list(NOTE_CATEGORIES))
        self.p17_category_combo.currentTextChanged.connect(self._p17_on_note_fields_changed)
        meta_row.addWidget(self.p17_category_combo, 1)
        editor_layout.addLayout(meta_row)

        timestamps_row = QHBoxLayout()
        timestamps_row.setSpacing(18)
        self.p17_created_lbl = QLabel('Created: -')
        self.set_theme_role(self.p17_created_lbl, 'muted')
        self.p17_updated_lbl = QLabel('Edited: -')
        self.set_theme_role(self.p17_updated_lbl, 'muted')
        timestamps_row.addWidget(self.p17_created_lbl)
        timestamps_row.addWidget(self.p17_updated_lbl)
        timestamps_row.addStretch()
        editor_layout.addLayout(timestamps_row)

        body_label = QLabel('Note')
        self.set_theme_role(body_label, 'section_title')
        editor_layout.addWidget(body_label)
        self.p17_body_edit = QPlainTextEdit()
        self.p17_body_edit.setPlaceholderText('Start typing to create a new note...')
        self.p17_body_edit.textChanged.connect(self._p17_on_note_fields_changed)
        editor_layout.addWidget(self.p17_body_edit, 1)

        content_splitter.addWidget(editor_panel)

        attachments_box = QGroupBox('Pictures')
        self.set_theme_role(attachments_box, 'panel')
        attachments_layout = QVBoxLayout(attachments_box)
        attachments_layout.setContentsMargins(6, 8, 6, 6)
        attachments_layout.setSpacing(6)

        attachments_btn_row = QHBoxLayout()
        self.p17_add_image_btn = QPushButton('Add Picture')
        self.p17_add_image_btn.clicked.connect(self._p17_add_images)
        self.p17_remove_image_btn = QPushButton('Remove Picture')
        self.p17_remove_image_btn.clicked.connect(self._p17_remove_selected_image)
        self.p17_open_image_btn = QPushButton('Open Picture')
        self.p17_open_image_btn.clicked.connect(self._p17_open_selected_image)
        attachments_btn_row.addWidget(self.p17_add_image_btn)
        attachments_btn_row.addWidget(self.p17_remove_image_btn)
        attachments_btn_row.addWidget(self.p17_open_image_btn)
        attachments_btn_row.addStretch()
        attachments_layout.addLayout(attachments_btn_row)

        self.p17_image_list = QListWidget()
        self.p17_image_list.setViewMode(QListView.ViewMode.IconMode)
        self.p17_image_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.p17_image_list.setMovement(QListView.Movement.Static)
        self.p17_image_list.setWrapping(True)
        self.p17_image_list.setWordWrap(True)
        self.p17_image_list.setSpacing(8)
        self.p17_image_list.setIconSize(QSize(128, 128))
        self.p17_image_list.setGridSize(QSize(156, 168))
        self.p17_image_list.currentItemChanged.connect(self._p17_on_image_selection_changed)
        self.p17_image_preview = QLabel('No picture selected')
        self.p17_image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.p17_image_preview.setMinimumHeight(140)
        self.p17_image_preview.setMaximumHeight(180)
        self.p17_image_preview.setWordWrap(True)
        attachments_layout.addWidget(self.p17_image_preview)
        attachments_layout.addWidget(self.p17_image_list, 1)

        content_splitter.setStretchFactor(0, 2)
        content_splitter.setStretchFactor(1, 3)
        content_splitter.addWidget(attachments_box)
        content_splitter.setStretchFactor(2, 2)

        self.tz_combo.currentIndexChanged.connect(self._p17_refresh_timestamp_labels)
        self.time_fmt_btn.clicked.connect(self._p17_refresh_timestamp_labels)
        self._p17_refresh_note_list(prefer_blank_selection=self._p17_first_visit_blank_pending)
        if self.p17_note_list.count() == 0:
            self._p17_prepare_blank_editor()
            self.set_status_text(self.p17_status_lbl, 'No notes yet. Start typing a title or note body to create one.', status='muted')
        self._apply_notes_theme()

    def _p17_on_show(self) -> None:
        if self._p17_first_visit_blank_pending:
            self._p17_first_visit_blank_pending = False
            self._p17_startup_blank_mode = True
            self._p17_refresh_note_list(prefer_blank_selection=True)
        else:
            if self._p17_startup_blank_mode and not self._p17_selected_note_id:
                self._p17_startup_blank_mode = False
            self._p17_refresh_note_list(self._p17_selected_note_id)
        self._p17_refresh_timestamp_labels()
        self._p17_refresh_image_preview()

    def _p17_note_sort_key(self, note: dict[str, Any]) -> float:
        stamp = self._p17_parse_timestamp(note.get('updated_at')) or self._p17_parse_timestamp(note.get('created_at'))
        return stamp.timestamp() if stamp is not None else 0.0

    def _p17_sorted_notes(self) -> list[dict[str, Any]]:
        return sorted(
            [note for note in self.notes_data if isinstance(note, dict)],
            key=lambda note: (self._p17_note_sort_key(note), str(note.get('id', ''))),
            reverse=True,
        )

    def _p17_refresh_note_list(self, selected_note_id: str | None = None, *, reload_editor: bool = True, prefer_blank_selection: bool = False) -> None:
        target_id = selected_note_id if selected_note_id is not None else self._p17_selected_note_id
        notes = self._p17_sorted_notes()
        self.p17_note_list.blockSignals(True)
        self.p17_note_list.clear()
        target_item = None
        fallback_item = None
        for note in notes:
            item = QListWidgetItem(self._p17_note_item_text(note))
            item.setData(Qt.ItemDataRole.UserRole, str(note.get('id', '') or ''))
            item.setToolTip(self._p17_note_item_tooltip(note))
            item.setSizeHint(QSize(0, 58))
            self.p17_note_list.addItem(item)
            if fallback_item is None:
                fallback_item = item
            if str(note.get('id', '') or '') == str(target_id or ''):
                target_item = item
        if target_item is None and not prefer_blank_selection:
            target_item = fallback_item
        if target_item is not None:
            self.p17_note_list.setCurrentItem(target_item)
            self._p17_selected_note_id = str(target_item.data(Qt.ItemDataRole.UserRole) or '')
        else:
            self._p17_selected_note_id = None
        self.p17_note_list.blockSignals(False)
        self.p17_delete_btn.setEnabled(bool(self._p17_selected_note_id))

        if reload_editor:
            note = self._p17_get_note(self._p17_selected_note_id)
            if note is not None:
                self._p17_load_note(note)
            else:
                self._p17_prepare_blank_editor(show_all_images=prefer_blank_selection and bool(notes))

    def _p17_note_item_text(self, note: dict[str, Any]) -> str:
        title = self._p17_note_title(note)
        preview_source = str(note.get('body', '') or '').strip().replace('\n', ' ')
        preview = preview_source[:90] + ('...' if len(preview_source) > 90 else '')
        updated_text = self._p17_format_timestamp(note.get('updated_at'))
        category = str(note.get('category', NOTE_CATEGORIES[0]) or NOTE_CATEGORIES[0])
        line_1 = title
        line_2 = f'{category} | {updated_text}'
        return f'{line_1}\n{line_2}' if not preview else f'{line_1}\n{line_2}\n{preview}'

    def _p17_note_item_tooltip(self, note: dict[str, Any]) -> str:
        created_text = self._p17_format_timestamp(note.get('created_at'))
        updated_text = self._p17_format_timestamp(note.get('updated_at'))
        return (
            f'Category: {note.get("category", NOTE_CATEGORIES[0])}\n'
            f'Created: {created_text}\n'
            f'Edited: {updated_text}'
        )

    def _p17_note_title(self, note: dict[str, Any]) -> str:
        title = str(note.get('title', '') or '').strip()
        if title:
            return title
        body = str(note.get('body', '') or '').strip()
        if body:
            first_line = body.splitlines()[0].strip()
            if first_line:
                return first_line[:60] + ('...' if len(first_line) > 60 else '')
        return 'Untitled note'

    def _p17_get_note(self, note_id: Any) -> dict[str, Any] | None:
        target_id = str(note_id or '').strip()
        for note in self.notes_data:
            if isinstance(note, dict) and str(note.get('id', '') or '').strip() == target_id:
                return note
        return None

    def _p17_load_note(self, note: dict[str, Any] | None) -> None:
        self._p17_loading_note = True
        try:
            enabled = note is not None
            self._p17_set_editor_enabled(enabled)
            if note is None:
                self._p17_prepare_blank_editor()
                return
            self.p17_title_edit.setText(str(note.get('title', '') or ''))
            category = str(note.get('category', NOTE_CATEGORIES[0]) or NOTE_CATEGORIES[0])
            category_index = max(self.p17_category_combo.findText(category), 0)
            self.p17_category_combo.setCurrentIndex(category_index)
            self.p17_body_edit.setPlainText(str(note.get('body', '') or ''))
            self._p17_refresh_timestamp_labels(note)
            self._p17_load_images()
        finally:
            self._p17_loading_note = False
            self._p17_note_dirty = False

    def _p17_set_editor_enabled(self, enabled: bool) -> None:
        self.p17_title_edit.setEnabled(enabled)
        self.p17_category_combo.setEnabled(enabled)
        self.p17_body_edit.setEnabled(enabled)
        self.p17_add_image_btn.setEnabled(enabled)
        self.p17_remove_image_btn.setEnabled(enabled and self.p17_image_list.currentItem() is not None)
        self.p17_open_image_btn.setEnabled(enabled and self.p17_image_list.currentItem() is not None)

    def _p17_prepare_blank_editor(self, *, show_all_images: bool = False) -> None:
        self._p17_loading_note = True
        try:
            self.p17_title_edit.clear()
            self.p17_category_combo.setCurrentIndex(0)
            self.p17_body_edit.clear()
            self.p17_created_lbl.setText('Created: -')
            self.p17_updated_lbl.setText('Edited: -')
            self.p17_image_list.clear()
            self._p17_selected_note_id = None
            self._p17_selected_image_id = None
            self.p17_image_preview.setPixmap(QPixmap())
            self.p17_image_preview.setText('No picture selected')
        finally:
            self._p17_loading_note = False
            self._p17_note_dirty = False
        self.p17_title_edit.setEnabled(True)
        self.p17_category_combo.setEnabled(True)
        self.p17_body_edit.setEnabled(True)
        self.p17_add_image_btn.setEnabled(True)
        self.p17_remove_image_btn.setEnabled(False)
        self.p17_open_image_btn.setEnabled(False)
        if show_all_images:
            self._p17_load_images(select_fallback=False)

    def _p17_clear_editor(self) -> None:
        self._p17_loading_note = True
        try:
            self.p17_title_edit.clear()
            self.p17_category_combo.setCurrentIndex(0)
            self.p17_body_edit.clear()
            self.p17_created_lbl.setText('Created: -')
            self.p17_updated_lbl.setText('Edited: -')
            self.p17_image_list.clear()
            self._p17_selected_image_id = None
            self.p17_image_preview.setPixmap(QPixmap())
            self.p17_image_preview.setText('No picture selected')
        finally:
            self._p17_loading_note = False
            self._p17_note_dirty = False
        self._p17_set_editor_enabled(False)

    def _p17_on_note_selection_changed(self, current: Any, _previous: Any) -> None:
        if self._p17_internal_note_select:
            return
        target_id = str(current.data(Qt.ItemDataRole.UserRole) or '').strip() if current is not None else ''
        target_id = target_id or None
        if target_id == self._p17_selected_note_id:
            return
        self._p17_save_selected_note(refresh=False)
        if target_id:
            self._p17_startup_blank_mode = False
        self._p17_internal_note_select = True
        try:
            self._p17_selected_note_id = target_id
            self._p17_refresh_note_list(target_id)
        finally:
            self._p17_internal_note_select = False

    def _p17_on_note_fields_changed(self, *_: Any) -> None:
        if self._p17_loading_note:
            return
        if not self._p17_selected_note_id:
            title_text = self.p17_title_edit.text()
            body_text = self.p17_body_edit.toPlainText()
            if title_text or body_text:
                self._p17_create_note_from_editor()
            return
        self._p17_note_dirty = True
        self._p17_notes_save_timer.start(self._P17_SAVE_DEBOUNCE_MS)
        self.set_status_text(self.p17_status_lbl, 'Saving note changes...', status='muted')

    def _p17_save_selected_note(self, refresh: bool = True) -> None:
        if self._p17_loading_note:
            return
        note = self._p17_get_note(self._p17_selected_note_id)
        if note is None:
            self._p17_notes_save_timer.stop()
            self._p17_note_dirty = False
            return
        self._p17_notes_save_timer.stop()
        if self._p17_note_dirty:
            note['title'] = self.p17_title_edit.text()
            note['body'] = self.p17_body_edit.toPlainText()
            note['category'] = str(self.p17_category_combo.currentText() or NOTE_CATEGORIES[0])
            now_iso = self._p17_now_iso()
            if not str(note.get('created_at', '') or '').strip():
                note['created_at'] = now_iso
            note['updated_at'] = now_iso
        if not self._p17_note_has_meaningful_content(note):
            self._p17_note_dirty = False
            if self._p17_delete_note_by_id(str(note.get('id', '') or ''), refresh=refresh, prefer_blank_selection=True):
                self.set_status_text(self.p17_status_lbl, 'Empty note deleted.', status='warning')
            return
        if not self._p17_note_dirty and not refresh:
            return
        if self._p17_note_dirty:
            self.notes_data = save_notes_data(self.notes_data)
        self._p17_note_dirty = False
        if refresh:
            self._p17_refresh_note_list(self._p17_selected_note_id, reload_editor=False)
        self._p17_refresh_timestamp_labels(note)
        self.set_status_text(self.p17_status_lbl, 'Notes saved.', status='positive')

    def _p17_flush_pending_save(self) -> None:
        if getattr(self, '_p17_note_dirty', False) or self._p17_notes_save_timer.isActive() or self._p17_selected_note_id:
            self._p17_save_selected_note()

    def _p17_apply_runtime_notes_data(self, notes: Any = None) -> None:
        self._p17_notes_save_timer.stop()
        self._p17_note_dirty = False
        self._p17_first_visit_blank_pending = False
        self._p17_startup_blank_mode = False
        self._p17_startup_draft_note_id = None
        self.notes_data = list(notes) if isinstance(notes, list) else load_notes_data()
        selected_note_id = self._p17_selected_note_id if self._p17_get_note(self._p17_selected_note_id) is not None else None
        self._p17_refresh_note_list(selected_note_id)
        if self.p17_note_list.count() == 0:
            self._p17_prepare_blank_editor()

    def _p17_create_note_from_editor(self) -> None:
        title_text = self.p17_title_edit.text()
        body_text = self.p17_body_edit.toPlainText()
        if not title_text and not body_text:
            return
        focus_target = 'title' if self.p17_title_edit.hasFocus() else 'body' if self.p17_body_edit.hasFocus() else None
        note_id = uuid.uuid4().hex
        now_iso = self._p17_now_iso()
        self.notes_data.append({
            'id': note_id,
            'title': title_text,
            'body': body_text,
            'category': str(self.p17_category_combo.currentText() or NOTE_CATEGORIES[0]),
            'created_at': now_iso,
            'updated_at': now_iso,
            'images': [],
        })
        self.notes_data = save_notes_data(self.notes_data)
        if self._p17_startup_blank_mode:
            self._p17_startup_draft_note_id = note_id
        self._p17_startup_blank_mode = False
        self._p17_selected_note_id = note_id
        self._p17_refresh_note_list(note_id)
        if focus_target == 'title':
            self.p17_title_edit.setFocus()
            self.p17_title_edit.setCursorPosition(len(self.p17_title_edit.text()))
        elif focus_target == 'body':
            self.p17_body_edit.setFocus()
            cursor = self.p17_body_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.p17_body_edit.setTextCursor(cursor)
        self.set_status_text(self.p17_status_lbl, 'New note created.', status='positive')

    def _p17_create_note(self) -> None:
        self._p17_flush_pending_save()
        note_id = uuid.uuid4().hex
        now_iso = self._p17_now_iso()
        self.notes_data.append({
            'id': note_id,
            'title': '',
            'body': '',
            'category': NOTE_CATEGORIES[0],
            'created_at': now_iso,
            'updated_at': now_iso,
            'images': [],
        })
        self.notes_data = save_notes_data(self.notes_data)
        if self._p17_startup_blank_mode:
            self._p17_startup_draft_note_id = note_id
        self._p17_startup_blank_mode = False
        self._p17_selected_note_id = note_id
        self._p17_refresh_note_list(note_id)
        self.p17_title_edit.setFocus()
        self.set_status_text(self.p17_status_lbl, 'New note created.', status='positive')

    def _p17_delete_selected_note(self) -> None:
        note = self._p17_get_note(self._p17_selected_note_id)
        if note is None:
            return
        reply = QMessageBox.question(
            self,
            'Delete Note',
            f'Delete "{self._p17_note_title(note)}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._p17_notes_save_timer.stop()
        self._p17_note_dirty = False
        if self._p17_delete_note_by_id(str(note.get('id', '') or '')):
            self.set_status_text(self.p17_status_lbl, 'Note deleted.', status='warning')

    def _p17_note_directory(self, note_id: str) -> Any:
        return user_data_dir().joinpath('notes_images', str(note_id or '').strip())

    def _p17_add_images(self) -> None:
        note = self._p17_get_note(self._p17_selected_note_id)
        file_paths, _ = QFileDialog.getOpenFileNames(self, 'Attach Pictures', '', self._P17_IMAGE_FILTER)
        if not file_paths:
            return
        if note is not None:
            self._p17_save_selected_note(refresh=False)
            note = self._p17_get_note(self._p17_selected_note_id)
        if note is None:
            note_id = uuid.uuid4().hex
            now_iso = self._p17_now_iso()
            self.notes_data.append({
                'id': note_id,
                'title': '',
                'body': '',
                'category': str(self.p17_category_combo.currentText() or NOTE_CATEGORIES[0]),
                'created_at': now_iso,
                'updated_at': now_iso,
                'images': [],
            })
            self.notes_data = save_notes_data(self.notes_data)
            if self._p17_startup_blank_mode:
                self._p17_startup_draft_note_id = note_id
            self._p17_startup_blank_mode = False
            self._p17_selected_note_id = note_id
            self._p17_refresh_note_list(note_id)
            note = self._p17_get_note(note_id)
        if note is None:
            return
        note_dir = self._p17_note_directory(str(note.get('id', '') or ''))
        note_dir.mkdir(parents=True, exist_ok=True)
        added_count = 0
        for file_path in file_paths:
            source = Path(file_path)
            if not source.exists() or not source.is_file():
                continue
            target_name = f'{uuid.uuid4().hex}{source.suffix.lower()}'
            target_path = note_dir / target_name
            shutil.copy2(source, target_path)
            note.setdefault('images', []).append({
                'id': uuid.uuid4().hex,
                'name': source.name,
                'path': str(Path('notes_images') / str(note.get('id', '') or '') / target_name).replace('\\', '/'),
            })
            added_count += 1
        if added_count <= 0:
            self.set_status_text(self.p17_status_lbl, 'No pictures were attached.', status='warning')
            return
        note['updated_at'] = self._p17_now_iso()
        self.notes_data = save_notes_data(self.notes_data)
        selected_image_id = str(note.get('images', [])[-1].get('id', '') or '') if note.get('images') else None
        self._p17_refresh_note_list(self._p17_selected_note_id)
        self._p17_select_image(selected_image_id)
        self.set_status_text(self.p17_status_lbl, f'Attached {added_count} picture(s).', status='positive')

    def _p17_remove_selected_image(self) -> None:
        note, image = self._p17_get_selected_image_entry()
        if note is None:
            return
        if image is None:
            return
        note['images'] = [entry for entry in note.get('images', []) if str(entry.get('id', '') or '') != str(image.get('id', '') or '')]
        image_path = self._p17_resolve_image_path(image)
        if image_path.exists():
            try:
                image_path.unlink()
            except OSError:
                logger.warning('Unable to delete note image: %s', image_path)
        note['updated_at'] = self._p17_now_iso()
        if not self._p17_note_has_meaningful_content(note):
            if self._p17_delete_note_by_id(str(note.get('id', '') or ''), prefer_blank_selection=True):
                self.set_status_text(self.p17_status_lbl, 'Empty note deleted.', status='warning')
            return
        self.notes_data = save_notes_data(self.notes_data)
        self._p17_refresh_note_list(self._p17_selected_note_id)
        self.set_status_text(self.p17_status_lbl, 'Picture removed.', status='warning')

    def _p17_open_selected_image(self) -> None:
        note, image = self._p17_get_selected_image_entry()
        if note is None:
            return
        if image is None:
            return
        image_path = self._p17_resolve_image_path(image)
        if not image_path.exists():
            self.set_status_text(self.p17_status_lbl, 'Picture file is missing.', status='negative')
            return
        webbrowser.open(image_path.resolve().as_uri())

    def _p17_get_selected_image_entry(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        target_id = str(self._p17_selected_image_id or '').strip()
        if not target_id:
            return None, None
        for note in self._p17_sorted_notes():
            for image in note.get('images', []):
                if isinstance(image, dict) and str(image.get('id', '') or '').strip() == target_id:
                    return note, image
        return None, None

    def _p17_load_images(self, *, select_fallback: bool = True) -> None:
        image_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for note in self._p17_sorted_notes():
            for image in note.get('images', []):
                if isinstance(image, dict):
                    image_entries.append((note, image))
        selected_image_id = self._p17_selected_image_id
        self.p17_image_list.blockSignals(True)
        self.p17_image_list.clear()
        target_item = None
        fallback_item = None
        for note, image in image_entries:
            item = QListWidgetItem(str(image.get('name', 'Picture') or 'Picture'))
            item.setData(Qt.ItemDataRole.UserRole, str(image.get('id', '') or ''))
            item.setData(Qt.ItemDataRole.UserRole + 1, str(note.get('id', '') or ''))
            item.setToolTip(f'{self._p17_note_title(note)}\n{str(image.get("path", "") or "")}')
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            image_path = self._p17_resolve_image_path(image)
            if image_path.exists():
                pixmap = QPixmap(str(image_path))
                if not pixmap.isNull():
                    thumbnail = pixmap.scaled(
                        128,
                        128,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    item.setIcon(QIcon(thumbnail))
            item.setSizeHint(QSize(156, 168))
            self.p17_image_list.addItem(item)
            if fallback_item is None:
                fallback_item = item
            if str(image.get('id', '') or '') == str(selected_image_id or ''):
                target_item = item
        if target_item is None and select_fallback:
            target_item = fallback_item
        if target_item is not None:
            self.p17_image_list.setCurrentItem(target_item)
            self._p17_selected_image_id = str(target_item.data(Qt.ItemDataRole.UserRole) or '')
        else:
            self._p17_selected_image_id = None
        self.p17_image_list.blockSignals(False)
        self._p17_refresh_image_preview()

    def _p17_select_image(self, image_id: str | None) -> None:
        self._p17_selected_image_id = image_id
        self._p17_load_images()

    def _p17_on_image_selection_changed(self, current: Any, _previous: Any) -> None:
        self._p17_selected_image_id = str(current.data(Qt.ItemDataRole.UserRole) or '').strip() if current is not None else None
        target_note_id = str(current.data(Qt.ItemDataRole.UserRole + 1) or '').strip() if current is not None else ''
        if target_note_id and target_note_id != str(self._p17_selected_note_id or ''):
            self._p17_save_selected_note(refresh=False)
            self._p17_startup_blank_mode = False
            self._p17_selected_note_id = target_note_id
            self._p17_refresh_note_list(target_note_id)
            return
        self._p17_refresh_image_preview()

    def _p17_note_has_meaningful_content(self, note: dict[str, Any] | None) -> bool:
        if not isinstance(note, dict):
            return False
        if str(note.get('title', '') or '').strip():
            return True
        if str(note.get('body', '') or '').strip():
            return True
        images = note.get('images', [])
        return isinstance(images, list) and any(isinstance(image, dict) for image in images)

    def _p17_delete_note_by_id(self, note_id: str, *, refresh: bool = True, prefer_blank_selection: bool = False) -> bool:
        target_id = str(note_id or '').strip()
        if not target_id:
            return False
        note = self._p17_get_note(target_id)
        if note is None:
            return False
        if target_id == str(self._p17_startup_draft_note_id or ''):
            self._p17_startup_draft_note_id = None
        self.notes_data = [entry for entry in self.notes_data if str(entry.get('id', '') or '') != target_id]
        shutil.rmtree(self._p17_note_directory(target_id), ignore_errors=True)
        self.notes_data = save_notes_data(self.notes_data)
        if target_id == str(self._p17_selected_note_id or ''):
            self._p17_selected_note_id = None
            self._p17_selected_image_id = None
        if refresh:
            self._p17_refresh_note_list(prefer_blank_selection=prefer_blank_selection)
        return True

    def _p17_finalize_startup_draft_on_close(self) -> None:
        draft_id = str(self._p17_startup_draft_note_id or '').strip()
        if not draft_id:
            return
        note = self._p17_get_note(draft_id)
        if note is None:
            self._p17_startup_draft_note_id = None
            return
        if self._p17_note_has_meaningful_content(note):
            return
        self._p17_delete_note_by_id(draft_id, refresh=False)

    def _p17_resolve_image_path(self, image: dict[str, Any]) -> Any:
        relative_path = str(image.get('path', '') or '').strip().replace('\\', '/')
        return user_data_dir().joinpath(*Path(relative_path).parts)

    def _p17_refresh_image_preview(self) -> None:
        note, image = self._p17_get_selected_image_entry()
        self.p17_remove_image_btn.setEnabled(note is not None and image is not None)
        self.p17_open_image_btn.setEnabled(note is not None and image is not None)
        if image is None:
            self.p17_image_preview.setPixmap(QPixmap())
            self.p17_image_preview.setText('No picture selected')
            return
        image_path = self._p17_resolve_image_path(image)
        if not image_path.exists():
            self.p17_image_preview.setPixmap(QPixmap())
            self.p17_image_preview.setText('Picture file is missing')
            return
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self.p17_image_preview.setPixmap(QPixmap())
            self.p17_image_preview.setText('Unable to load picture preview')
            return
        width = max(self.p17_image_preview.width() - 12, 120)
        height = max(self.p17_image_preview.height() - 12, 120)
        scaled = pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.p17_image_preview.setText('')
        self.p17_image_preview.setPixmap(scaled)

    def _p17_parse_timestamp(self, value: Any) -> datetime.datetime | None:
        text = str(value or '').strip()
        if not text:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed

    def _p17_format_timestamp(self, value: Any) -> str:
        parsed = self._p17_parse_timestamp(value)
        if parsed is None:
            return '-'
        try:
            tzinfo = self._get_tzinfo(self.tz_combo.currentIndex()) if hasattr(self, '_get_tzinfo') else None
            if tzinfo is not None:
                parsed = parsed.astimezone(tzinfo)
        except Exception:
            pass
        time_fmt = '%b %d, %Y %I:%M:%S %p' if getattr(self, '_time_12h', False) else '%b %d, %Y %H:%M:%S'
        return parsed.strftime(time_fmt)

    def _p17_refresh_timestamp_labels(self, note: dict[str, Any] | None = None) -> None:
        target_note = note if isinstance(note, dict) else self._p17_get_note(self._p17_selected_note_id)
        if target_note is None:
            if hasattr(self, 'p17_created_lbl'):
                self.p17_created_lbl.setText('Created: -')
            if hasattr(self, 'p17_updated_lbl'):
                self.p17_updated_lbl.setText('Edited: -')
            return
        self.p17_created_lbl.setText(f'Created: {self._p17_format_timestamp(target_note.get("created_at"))}')
        self.p17_updated_lbl.setText(f'Edited: {self._p17_format_timestamp(target_note.get("updated_at"))}')

    def _p17_now_iso(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _apply_notes_theme(self) -> None:
        bg = self.theme_color('panel_background')
        border = self.theme_color('panel_border')
        text = self.theme_color('text_primary')
        muted = self.theme_color('text_secondary')
        list_style = (
            f'QListWidget {{ background-color: {bg}; color: {text}; border: 1px solid {border}; }}'
            f'QListWidget::item:selected {{ background-color: {self.theme_color("accent")}; color: {self.theme_color("background_primary")}; }}'
        )
        editor_style = (
            f'background-color: {bg}; color: {text}; border: 1px solid {border}; border-radius: 4px;'
        )
        preview_style = (
            f'background-color: {bg}; color: {muted}; border: 1px solid {border}; border-radius: 4px;'
        )
        if hasattr(self, 'p17_note_list'):
            self.p17_note_list.setStyleSheet(list_style)
        if hasattr(self, 'p17_image_list'):
            self.p17_image_list.setStyleSheet(list_style)
        if hasattr(self, 'p17_title_edit'):
            self.p17_title_edit.setStyleSheet(editor_style)
        if hasattr(self, 'p17_body_edit'):
            self.p17_body_edit.setStyleSheet(editor_style)
        if hasattr(self, 'p17_category_combo'):
            self.p17_category_combo.setStyleSheet(editor_style)
        if hasattr(self, 'p17_image_preview'):
            self.p17_image_preview.setStyleSheet(preview_style)
        if hasattr(self, 'p17_status_lbl'):
            self.set_status_text(self.p17_status_lbl, self.p17_status_lbl.text(), status=self.p17_status_lbl.property('bt_status') or 'muted')
