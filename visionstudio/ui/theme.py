"""UI design tokens and the application stylesheet, in a dark and a light mode.

Rule for every surface: dark background -> light text, light background -> dark text. Widgets read
the tokens as `theme.TEXT`, `theme.PANEL`, ... at build time; after set_mode() the main window is
rebuilt so every widget picks up the new values.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

MODES = ("dark", "light")
MONO = "Consolas, 'DejaVu Sans Mono', monospace"

PALETTES = {
    "dark": dict(
        BG="#181818", BG_CANVAS="#1e1e1e", PANEL="#252526", PANEL_HI="#2d2d2d", HEADER="#222222",
        BORDER="#333333", BORDER_HI="#3c3c3c", ACCENT="#007acc", ACCENT_HOVER="#0062a3",
        TEXT="#e5e5e5", TEXT_STRONG="#ffffff", TEXT_DIM="#a8b0bb", DISABLED="#6b7280",
        OK="#34d399", NG="#f87171", WARN="#fbbf24", INFO="#60a5fa",
        OK_BG="#0c2a20", NG_BG="#33141a", WARN_BG="#33270f",
        HOVER="#383838", SELECT="#094771", INPUT_BG="#1e1e1e", INPUT_BORDER="#4b4b4b", ALT_ROW="#2a2a2b",
        SCROLL="#4b4b4b", NODE_FILL="#2d2d2d", NODE_HEAD="#3c3c3c", NODE_BORDER="#555555", GRID_DOT="#333333",
    ),
    "light": dict(
        BG="#e5e7eb", BG_CANVAS="#f3f4f6", PANEL="#ffffff", PANEL_HI="#e5e7eb", HEADER="#ffffff",
        BORDER="#d1d5db", BORDER_HI="#9ca3af", ACCENT="#0066b8", ACCENT_HOVER="#00528f",
        TEXT="#111827", TEXT_STRONG="#000000", TEXT_DIM="#4b5563", DISABLED="#9ca3af",
        OK="#047857", NG="#b91c1c", WARN="#b45309", INFO="#1d4ed8",
        OK_BG="#d1fae5", NG_BG="#fee2e2", WARN_BG="#fef3c7",
        HOVER="#d1d5db", SELECT="#bfdbfe", INPUT_BG="#ffffff", INPUT_BORDER="#9ca3af", ALT_ROW="#f9fafb",
        SCROLL="#9ca3af", NODE_FILL="#ffffff", NODE_HEAD="#e5e7eb", NODE_BORDER="#9ca3af", GRID_DOT="#c4c8cf",
    ),
}
# Surfaces that keep one colour in both modes; their text colour is fixed to match.
ON_COLOR = "#ffffff"          # text on accent / green / red / amber buttons, the footer and the logo
BTN_START, BTN_STOP, BTN_AMBER = "#047857", "#dc2626", "#b45309"
IMAGE_BG, IMAGE_TEXT = "#000000", "#d1d5db"      # camera / image areas stay black with light text
BAR_EXTRA = ("#8b5cf6", "#0d9488")

mode = "dark"
globals().update(PALETTES["dark"])


def set_mode(new_mode: str) -> None:
    """Switch the token values. Call apply_theme() and rebuild the window afterwards."""
    global mode
    mode = new_mode if new_mode in MODES else "dark"
    globals().update(PALETTES[mode])


def result_color(status: str) -> str:
    return {"OK": OK, "NG": NG, "ERROR": WARN}.get(status, TEXT)


def result_bg(status: str) -> str:
    return {"OK": OK_BG, "NG": NG_BG, "ERROR": WARN_BG}.get(status, PANEL)


def build_qss() -> str:
    return f"""
* {{ color: {TEXT}; font-size: 12px; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QDialog, QMessageBox, QInputDialog {{ background: {PANEL}; }}
QWidget#view {{ background: {BG_CANVAS}; }}
QWidget#header {{ background: {HEADER}; border-bottom: 1px solid {BORDER}; }}
QWidget#footer {{ background: {ACCENT}; }}
QWidget#footer QLabel {{ color: {ON_COLOR}; font-family: {MONO}; font-size: 11px; }}
QWidget#side {{ background: {PANEL}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#logo {{ background: {ACCENT}; color: {ON_COLOR}; font-weight: bold; font-size: 13px;
               padding: 5px 10px; border-radius: 4px; letter-spacing: 1px; }}
QLabel#chip {{ background: {PANEL_HI}; border: 1px solid {BORDER_HI}; border-radius: 4px; padding: 4px 9px; }}
QLabel#h1 {{ font-size: 17px; font-weight: bold; color: {TEXT_STRONG}; }}
QLabel#sub, QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#caption {{ color: {TEXT_DIM}; font-size: 11px; font-weight: bold; }}
QLabel#section {{ color: {TEXT}; font-size: 11px; font-weight: bold; }}
QLabel#value {{ font-family: {MONO}; font-size: 28px; font-weight: 900; }}
QPushButton {{ background: {PANEL_HI}; border: 1px solid {BORDER_HI}; border-radius: 4px;
               padding: 6px 12px; font-weight: 600; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:disabled {{ color: {DISABLED}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: {ON_COLOR}; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {PANEL_HI}; color: {DISABLED}; border: 1px solid {BORDER_HI}; }}
QPushButton#start {{ background: {BTN_START}; border: none; color: {ON_COLOR}; }}
QPushButton#stop {{ background: {BTN_STOP}; border: none; color: {ON_COLOR}; }}
QPushButton#start:disabled, QPushButton#stop:disabled {{ background: {PANEL_HI}; color: {DISABLED}; }}
QPushButton#amber {{ background: {BTN_AMBER}; border: none; color: {ON_COLOR}; }}
QPushButton#amber:!checked {{ background: {PANEL_HI}; border: 1px solid {BORDER_HI}; color: {TEXT}; }}
QPushButton#tab {{ background: transparent; border: none; color: {TEXT_DIM}; padding: 6px 11px; }}
QPushButton#tab:hover {{ background: {PANEL_HI}; color: {TEXT}; }}
QPushButton#tab:checked {{ background: {ACCENT}; color: {ON_COLOR}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {INPUT_BG}; border: 1px solid {INPUT_BORDER}; border-radius: 4px; padding: 4px 7px;
    selection-background-color: {ACCENT}; selection-color: {ON_COLOR}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {DISABLED}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT}; selection-background-color: {ACCENT};
    selection-color: {ON_COLOR}; }}
QTreeWidget, QTableWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
    gridline-color: {BORDER}; alternate-background-color: {ALT_ROW}; outline: none; }}
QTreeWidget::item {{ padding: 5px 2px; }}
QTreeWidget::item:hover, QTableWidget::item:hover {{ background: {HOVER}; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {SELECT}; color: {TEXT_STRONG}; }}
QHeaderView::section {{ background: {PANEL_HI}; color: {TEXT_DIM}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 7px; font-size: 10px; font-weight: bold; }}
QTableCornerButton::section {{ background: {PANEL_HI}; border: none; }}
QProgressBar {{ background: {BG}; border: 1px solid {INPUT_BORDER}; border-radius: 5px; height: 10px; }}
QProgressBar::chunk {{ background: {OK}; border-radius: 4px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {TEXT_DIM}; padding: 8px 16px; font-weight: bold; border-radius: 4px; }}
QTabBar::tab:selected {{ background: {ACCENT}; color: {ON_COLOR}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle {{ background: {SCROLL}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: {BORDER}; }}
QToolTip {{ background: {PANEL_HI}; color: {TEXT}; border: 1px solid {BORDER_HI}; }}
QMenu {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER_HI}; }}
QMenu::item {{ padding: 5px 22px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {ON_COLOR}; }}
QMenu::item:disabled {{ color: {DISABLED}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; }}
"""


def _palette() -> QPalette:
    """Qt palette for everything the stylesheet does not reach (native dialogs, item views)."""
    pal = QPalette()
    roles = QPalette.ColorRole
    for role, color in ((roles.Window, PANEL), (roles.WindowText, TEXT), (roles.Base, INPUT_BG),
                        (roles.AlternateBase, ALT_ROW), (roles.Text, TEXT), (roles.Button, PANEL_HI),
                        (roles.ButtonText, TEXT), (roles.BrightText, TEXT_STRONG), (roles.Highlight, ACCENT),
                        (roles.HighlightedText, ON_COLOR), (roles.ToolTipBase, PANEL_HI), (roles.ToolTipText, TEXT),
                        (roles.PlaceholderText, DISABLED), (roles.Link, INFO)):
        pal.setColor(role, QColor(color))
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(DISABLED))
    return pal


def apply_theme(app: QApplication, new_mode: str | None = None) -> None:
    if new_mode is not None:
        set_mode(new_mode)
    app.setStyle("Fusion")
    font = QFont("Segoe UI")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    app.setPalette(_palette())
    app.setStyleSheet(build_qss())