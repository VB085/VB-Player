from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont
from PyQt6.QtCore import Qt, QSettings
import sys
from pathlib import Path

THEME_DIR = Path(__file__).parent / "ui" / "themes"

ACCENTS = {
    "purple": QColor("#7c3aed"),
    "blue":   QColor("#007AFF"),
    "green":  QColor("#10b981"),
    "orange": QColor("#f59e0b"),
    "pink":   QColor("#ec4899"),
    "red":    QColor("#ef4444"),
}

DEFAULT_DARK_ACCENT = "purple"
DEFAULT_LIGHT_ACCENT = "blue"

# Module-level cache updated by apply_theme() — single source of truth
_theme_mode: str = ""
_accent_name: str = ""


def _init_theme_cache():
    global _theme_mode, _accent_name
    s = QSettings("VBPlayer", "VB Player")
    _theme_mode = str(s.value("theme_mode", "dark") or "dark")
    _accent_name = str(s.value("accent", "purple") or "purple")


def _build_dark_palette(accent: QColor) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#000000"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#d0d0d0"))
    p.setColor(QPalette.ColorRole.Base, QColor("#080808"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#050505"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#141414"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#d0d0d0"))
    p.setColor(QPalette.ColorRole.Text, QColor("#d0d0d0"))
    p.setColor(QPalette.ColorRole.Button, QColor("#0f0f0f"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#d0d0d0"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Link, accent.lighter(130))
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#555555"))
    return p

def _build_light_palette(accent: QColor) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#333333"))
    p.setColor(QPalette.ColorRole.Base, QColor("#fafafa"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#f5f5f5"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#333333"))
    p.setColor(QPalette.ColorRole.Text, QColor("#333333"))
    p.setColor(QPalette.ColorRole.Button, QColor("#f0f0f0"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#333333"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#000000"))
    p.setColor(QPalette.ColorRole.Link, accent.darker(110))
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#999999"))
    return p

def apply_theme(app: QApplication, mode: str = "dark", accent_name: str = "purple"):
    global _theme_mode, _accent_name
    _theme_mode = mode
    _accent_name = accent_name
    accent = ACCENTS.get(accent_name, ACCENTS["purple"])
    if mode == "light":
        app.setPalette(_build_light_palette(accent))
        qss = (THEME_DIR / "light.qss").read_text(encoding="utf-8")
    else:
        app.setPalette(_build_dark_palette(accent))
        qss = (THEME_DIR / "dark_purple.qss").read_text(encoding="utf-8")
    # Inject accent into QSS via placeholders
    qss = qss.replace("@ACCENT@", accent.name())
    qss = qss.replace("@ACCENT_LIGHT@", accent.lighter(130).name())
    qss = qss.replace("@ACCENT_DARK@", accent.darker(120).name())
    app.setStyleSheet(qss)

def current_accent() -> QColor:
    return ACCENTS.get(_accent_name, ACCENTS["purple"])

def current_accent_name() -> str:
    return _accent_name or "purple"

def current_theme_mode() -> str:
    return _theme_mode or "dark"

def rgba_hex(r: int, g: int, b: int, a: float) -> str:
    """rgba(r, g, b, a) → #AARRGGBB for Qt QSS compatibility."""
    return f"#{int(a * 255):02x}{r:02x}{g:02x}{b:02x}"

def create_app() -> QApplication:
    app = QApplication(sys.argv)
    app.setApplicationName("VB Player")
    app.setOrganizationName("VBPlayer")
    font = QFont("HarmonyOS Sans SC", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    _init_theme_cache()
    apply_theme(app, _theme_mode, _accent_name)
    return app
