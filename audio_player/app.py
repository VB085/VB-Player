from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont, QPainter, QPainterPath, QPixmap, QIcon
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
    """Adwaita-dark inspired palette — blends with GNOME system theme."""
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#242424"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#eeeeee"))
    p.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#2d2d2d"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#363636"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#eeeeee"))
    p.setColor(QPalette.ColorRole.Text, QColor("#eeeeee"))
    p.setColor(QPalette.ColorRole.Button, QColor("#2d2d2d"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#eeeeee"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Link, accent.lighter(130))
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#777777"))
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
    qss = qss.replace("@ACCENT_DARKER@", accent.darker(150).name())
    qss = qss.replace("@ACCENT_DARK@", accent.darker(120).name())
    qss = qss.replace("@ACCENT_LIGHT@", accent.lighter(130).name())
    qss = qss.replace("@ACCENT@", accent.name())
    app.setStyleSheet(qss)

_dynamic_accent: QColor | None = None


def set_dynamic_accent(color: QColor):
    """Apply an album-art-derived accent. Cleared when user manually picks accent."""
    global _dynamic_accent, _accent_name
    ACCENTS["dynamic"] = color
    _dynamic_accent = color
    # Only apply if user hasn't manually locked in a different accent
    s = QSettings("VBPlayer", "VB Player")
    accent_source = str(s.value("accent_source", "manual") or "manual")
    if accent_source != "manual" or _accent_name == "dynamic":
        _accent_name = "dynamic"
        apply_theme(QApplication.instance(), _theme_mode, "dynamic")


def clear_dynamic_accent():
    """Revert to user's chosen static accent."""
    global _dynamic_accent, _accent_name
    _dynamic_accent = None
    s = QSettings("VBPlayer", "VB Player")
    _accent_name = str(s.value("accent", "purple") or "purple")
    apply_theme(QApplication.instance(), _theme_mode, _accent_name)


def current_accent() -> QColor:
    if _dynamic_accent and _accent_name == "dynamic":
        return _dynamic_accent
    return ACCENTS.get(_accent_name, ACCENTS["purple"])

def current_accent_name() -> str:
    return _accent_name or "purple"

def current_theme_mode() -> str:
    return _theme_mode or "dark"

def rgba_hex(r: int, g: int, b: int, a: float) -> str:
    """rgba(r, g, b, a) → #AARRGGBB for Qt QSS compatibility."""
    return f"#{int(a * 255):02x}{r:02x}{g:02x}{b:02x}"

_theme_tracker = None


def start_system_theme_tracking():
    """Start following system theme if available."""
    global _theme_tracker
    from audio_player.platform import create_theme_tracker
    _theme_tracker = create_theme_tracker()
    if _theme_tracker:
        _theme_tracker.systemThemeChanged.connect(_on_system_theme_changed)
        _theme_tracker.systemAccentChanged.connect(_on_system_accent_changed)
        _theme_tracker.start_tracking()


def _on_system_theme_changed(mode: str):
    """System dark/light changed."""
    # Only follow system if user hasn't manually overridden
    s = QSettings("VBPlayer", "VB Player")
    theme_source = str(s.value("theme_source", "manual") or "manual")
    if theme_source == "system":
        global _theme_mode, _accent_name
        _theme_mode = mode
        apply_theme(QApplication.instance(), mode, _accent_name)


def _on_system_accent_changed(accent: QColor):
    """System accent color changed."""
    s = QSettings("VBPlayer", "VB Player")
    accent_source = str(s.value("accent_source", "manual") or "manual")
    if accent_source == "system":
        # Find or add the accent to our palette
        global _accent_name
        accent_name = accent.name()
        for name, c in ACCENTS.items():
            if c.name() == accent_name:
                _accent_name = name
                break
        else:
            ACCENTS["system"] = accent
            _accent_name = "system"
        apply_theme(QApplication.instance(), _theme_mode, _accent_name)


def _generate_icon() -> QIcon:
    pix = QPixmap(256, 256)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(12, 12, 232, 232, 48, 48)
    p.fillPath(path, QColor("#7c3aed"))
    f = QFont()
    f.setPointSize(120)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "V")
    p.end()
    return QIcon(pix)


def create_app() -> QApplication:
    from audio_player.platform import get_system_font
    app = QApplication(sys.argv)
    app.setApplicationName("VB Player")
    app.setOrganizationName("VBPlayer")
    app.setWindowIcon(_generate_icon())
    app.setFont(get_system_font())
    _init_theme_cache()
    apply_theme(app, _theme_mode, _accent_name)
    start_system_theme_tracking()
    return app
