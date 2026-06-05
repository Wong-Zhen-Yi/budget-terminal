from __future__ import annotations

from ..dependencies import QObject, QPalette, QColor, Qt, pyqtSignal
from .theme_tokens import ThemeTokens
from .trading_dark_theme import TRADING_DARK_THEME


DEFAULT_THEME_ID = "trading_dark"
THEME_REGISTRY: dict[str, ThemeTokens] = {
    "trading_dark": TRADING_DARK_THEME,
}


def build_theme_stylesheet(theme: ThemeTokens) -> str:
    return f"""
QMainWindow, QWidget {{
    background: {theme.background_primary};
    color: {theme.text_primary};
}}
QLabel {{
    background: transparent;
}}
QWidget[bt_role="panel"], QGroupBox[bt_role="panel"] {{
    background: {theme.panel_background};
    border: 1px solid {theme.panel_border};
    border-radius: 6px;
}}
QFrame[bt_role="summary_chip"] {{
    background: {theme.background_secondary};
    border: 1px solid {theme.panel_border};
    border-radius: 6px;
}}
QGroupBox[bt_role="panel"] {{
    margin-top: 10px;
    padding-top: 10px;
    font-weight: 600;
    color: {theme.text_secondary};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QLabel[bt_role="page_title"] {{
    color: {theme.text_primary};
    font-size: 18px;
    font-weight: 700;
}}
QLabel[bt_role="section_title"] {{
    color: {theme.text_secondary};
    font-size: 13px;
    font-weight: 700;
}}
QLabel[bt_role="card_title"] {{
    color: {theme.text_secondary};
    font-size: 12px;
    font-weight: 700;
}}
QLabel[bt_role="muted"], QLabel[bt_role="status_muted"] {{
    color: {theme.text_muted};
}}
QLabel[bt_role="accent"] {{
    color: {theme.accent};
}}
QLabel[bt_role="metric"] {{
    color: {theme.warning};
    font-size: 15px;
    font-weight: 700;
}}
QLabel[bt_role="badge"] {{
    background: {theme.background_secondary};
    border: 1px solid {theme.panel_border};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 700;
    color: {theme.text_secondary};
}}
QLabel[bt_role="summary_chip_label"] {{
    color: {theme.text_muted};
    font-size: 11px;
    font-weight: 700;
}}
QLabel[bt_role="index"] {{
    background: {theme.panel_background};
    border: 1px solid {theme.panel_border};
    border-radius: 4px;
    padding: 4px 8px;
    font-weight: 700;
}}
QPushButton {{
    background: {theme.button_bg};
    color: {theme.text_primary};
    border: 1px solid {theme.panel_border};
    border-radius: 4px;
    padding: 4px 4px;
}}
QPushButton:hover {{
    background: {theme.button_hover_bg};
}}
QPushButton:checked, QPushButton[bt_checked="true"] {{
    background: {theme.button_checked_bg};
    border-color: {theme.button_checked_border};
    color: {theme.text_primary};
    font-weight: 700;
}}
QPushButton[bt_variant="accent"] {{
    background: {theme.accent_soft};
    color: {theme.accent};
    border-color: {theme.accent};
    font-weight: 700;
}}
QPushButton[bt_variant="positive"] {{
    background: {theme.accent_positive_bg};
    color: {theme.accent_positive};
    border-color: {theme.accent_positive};
    font-weight: 700;
}}
QPushButton[bt_variant="danger"] {{
    background: {theme.accent_negative_bg};
    color: {theme.accent_negative};
    border-color: {theme.accent_negative};
    font-weight: 700;
}}
QLineEdit, QComboBox, QDoubleSpinBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {{
    background: {theme.input_bg};
    color: {theme.text_primary};
    border: 1px solid {theme.input_border};
    border-radius: 4px;
    selection-background-color: {theme.selected_bg};
    alternate-background-color: {theme.table_row_alt_bg};
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {theme.input_focus_border};
}}
QDoubleSpinBox[bt_role="cash_input"] {{
    background: transparent;
    border: 0;
    color: {theme.warning};
    font-size: 13px;
    font-weight: 700;
}}
QDoubleSpinBox[bt_role="cash_input"]:focus {{
    background: {theme.input_bg};
    border: 1px solid {theme.input_focus_border};
}}
QComboBox::drop-down {{
    border: none;
}}
QTabWidget::pane {{
    border: 1px solid {theme.panel_border};
    background: {theme.panel_background};
}}
QTabBar::tab {{
    background: {theme.background_secondary};
    color: {theme.text_muted};
    padding: 6px 12px;
    border: 1px solid {theme.panel_border};
    border-bottom: none;
    min-width: 72px;
}}
QTabBar::tab:selected {{
    background: {theme.panel_background};
    color: {theme.text_primary};
}}
QHeaderView::section {{
    background: {theme.table_header_bg};
    color: {theme.text_secondary};
    border: 0;
    border-bottom: 1px solid {theme.panel_border};
    padding: 4px 6px;
    font-weight: 700;
}}
QTableWidget {{
    background: {theme.table_row_bg};
    gridline-color: {theme.gridline};
}}
QTableWidget::item {{
    padding: 2px 4px;
}}
QTableWidget::item:selected, QListWidget::item:selected {{
    background: {theme.selected_bg};
}}
QListWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {theme.panel_border};
}}
QListWidget::item:hover {{
    background: {theme.hover_bg};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {theme.background_secondary};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {theme.panel_border};
    min-height: 32px;
    border-radius: 6px;
}}
QSplitter::handle {{
    background: {theme.background_secondary};
}}
"""


class ThemeManager(QObject):
    theme_changed = pyqtSignal(str)

    def __init__(self, app: object) -> None:
        super().__init__()
        self.app = app
        self._themes: dict[str, ThemeTokens] = dict(THEME_REGISTRY)
        self.current_theme_id = DEFAULT_THEME_ID
        self.current_theme = self._themes[DEFAULT_THEME_ID]

    def theme(self, theme_id: str | None = None) -> ThemeTokens:
        return self._themes.get(theme_id or DEFAULT_THEME_ID, self.current_theme)

    def load_initial_theme_id(self) -> str:
        return DEFAULT_THEME_ID

    def apply_theme(self, theme_id: str | None = None) -> str:
        theme = self._themes[DEFAULT_THEME_ID]
        self.current_theme_id = DEFAULT_THEME_ID
        self.current_theme = theme
        self.app.setPalette(self._build_palette(theme))
        self.app.setStyleSheet(build_theme_stylesheet(theme))
        self.theme_changed.emit(DEFAULT_THEME_ID)
        return DEFAULT_THEME_ID

    def _build_palette(self, theme: ThemeTokens) -> QPalette:
        palette = QPalette()
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Window, QColor(theme.background_primary))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.WindowText, QColor(theme.text_primary))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Base, QColor(theme.input_bg))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.AlternateBase, QColor(theme.table_row_alt_bg))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.ToolTipBase, QColor(theme.panel_background))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.ToolTipText, QColor(theme.text_primary))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Text, QColor(theme.text_primary))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Button, QColor(theme.button_bg))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.ButtonText, QColor(theme.text_primary))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.BrightText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Highlight, QColor(theme.selected_bg))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.HighlightedText, QColor(theme.text_primary))
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.PlaceholderText, QColor(theme.text_muted))
        return palette
