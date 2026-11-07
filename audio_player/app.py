from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont, QPainter, QPainterPath, QPixmap, QIcon
from PyQt6.QtCore import Qt, QSettings, QTimer
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
    global _theme_mode, _accent_name, _applied_qss_key
    _theme_mode = mode
    _accent_name = accent_name
    accent = ACCENTS.get(accent_name, ACCENTS["purple"])
    if mode == "light":
        app.setPalette(_build_light_palette(accent))
    else:
        app.setPalette(_build_dark_palette(accent))
    _notify_palette_applied()  # Qt resets the DWM dark flag on any palette
    #                       change — correctors run before the event loop
    key, qss = _composed_qss(mode, accent)
    if key != _applied_qss_key:
        app.setStyleSheet(qss)
        _applied_qss_key = key

# Surface colors: opaque normally; translucent tints when a DWM backdrop
# (Win11 Mica/Acrylic) shows through the window.
_surface_translucent = False

_SURFACE_TOKENS = {
    ("dark", False):  {"@SURFACE_SIDE@": "#1e1e1e"},
    ("dark", True):   {"@SURFACE_SIDE@": "rgba(30,30,30,170)"},
    ("light", False): {"@SURFACE_SIDE@": "#f5f5f5",
                       "@SURFACE_CENTRAL@": "#ffffff"},
    ("light", True):  {"@SURFACE_SIDE@": "rgba(250,250,250,205)",
                       "@SURFACE_CENTRAL@": "rgba(255,255,255,140)"},
}


# Called synchronously after EVERY app.setPalette() below. Qt's Windows
# platform plugin resets DWMWA_USE_IMMERSIVE_DARK_MODE on any effective
# palette change (regardless of colors — verified empirically), which
# flips Mica to its white variant. Correctors registered here re-assert
# the flag in the same event-loop iteration, before DWM ever composes a
# wrong frame.
_after_palette_applied: list = []


def on_palette_applied(callback):
    """Register callback() to run right after every palette application."""
    _after_palette_applied.append(callback)


def _notify_palette_applied():
    for cb in list(_after_palette_applied):
        cb()


def surface_translucent() -> bool:
    """True when big surfaces should be translucent over a DWM backdrop."""
    return _surface_translucent


def set_surface_translucent(enabled: bool) -> None:
    """Toggle translucent surface colors for DWM-backdrop mode; recomposes QSS."""
    global _surface_translucent
    enabled = bool(enabled)
    if enabled == _surface_translucent:
        return
    _surface_translucent = enabled
    app = QApplication.instance()
    if app is not None:
        apply_theme(app, _theme_mode, _accent_name)


_qss_cache: dict[str, str] = {}

def _qss_text(mode: str) -> str:
    if mode not in _qss_cache:
        path = THEME_DIR / ("light.qss" if mode == "light" else "dark_purple.qss")
        _qss_cache[mode] = path.read_text(encoding="utf-8")
    return _qss_cache[mode]

# Fully-composed QSS (accent placeholders already substituted), keyed by
# (theme, accent) — avoids re-running replace chains and, more importantly,
# lets callers skip app.setStyleSheet() entirely when nothing changed.
_qss_composed_cache: dict[tuple, str] = {}
_applied_qss_key: tuple | None = None

def _composed_qss(mode: str, accent: QColor) -> tuple[tuple, str]:
    key = (mode, accent.name(), _surface_translucent)
    qss = _qss_composed_cache.get(key)
    if qss is None:
        if len(_qss_composed_cache) > 64:
            _qss_composed_cache.clear()
        qss = _qss_text(mode)
        qss = qss.replace("@ACCENT_DARKER@", accent.darker(150).name())
        qss = qss.replace("@ACCENT_DARK@", accent.darker(120).name())
        qss = qss.replace("@ACCENT_LIGHT@", accent.lighter(130).name())
        qss = qss.replace("@ACCENT@", accent.name())
        for tok, val in _SURFACE_TOKENS.get((mode, _surface_translucent), {}).items():
            qss = qss.replace(tok, val)
        _qss_composed_cache[key] = qss
    return key, qss

_dynamic_accent: QColor | None = None
_pending_color: QColor | None = None
_pending_timer: QTimer | None = None
_anim_timer: QTimer | None = None
_anim_from: QColor | None = None
_anim_to: QColor | None = None
_anim_step: int = 0
_DEBOUNCE = 100
_ANIM_STEPS = 12
_ANIM_MS = 50  # 600ms
_on_anim_tick: list = []  # lightweight — just notifies, no QSS work


def _color_distance(a: QColor, b: QColor) -> float:
    return ((a.red() - b.red()) ** 2 + (a.green() - b.green()) ** 2 +
            (a.blue() - b.blue()) ** 2) ** 0.5


def set_dynamic_accent(color: QColor):
    global _accent_name, _pending_color, _pending_timer
    s = QSettings("VBPlayer", "VB Player")
    if str(s.value("dynamic_accent_enabled", "true")).lower() != "true":
        return
    _accent_name = "dynamic"
    ACCENTS["dynamic"] = color
    current = _dynamic_accent or ACCENTS.get("purple", QColor("#7c3aed"))
    if _color_distance(current, color) < 20:
        return
    _pending_color = color
    if _pending_timer is None:
        _pending_timer = QTimer(QApplication.instance())
        _pending_timer.setSingleShot(True)
        _pending_timer.timeout.connect(_commit_accent)
    _pending_timer.start(_DEBOUNCE)


def _commit_accent():
    global _pending_color, _dynamic_accent, _anim_timer, _anim_from, _anim_to, _anim_step
    global _applied_qss_key
    if _pending_color is None:
        return
    to_color = _pending_color
    _pending_color = None
    if _dynamic_accent:
        from_color = _dynamic_accent.toRgb()
    else:
        g = int(to_color.red() * 0.3 + to_color.green() * 0.59 + to_color.blue() * 0.11)
        from_color = QColor(g, g, g).toRgb()
    to_color = to_color.toRgb()
    _anim_from = from_color
    _anim_to = to_color
    _anim_step = 0
    _dynamic_accent = QColor(from_color)
    ACCENTS["dynamic"] = QColor(from_color)
    app = QApplication.instance()
    c = QColor(from_color)
    # No palette write here: subscribers repaint via _on_anim_tick, and any
    # effective app.setPalette() makes Qt reset DWMWA_USE_IMMERSIVE_DARK_MODE
    # (Mica flashes white). The palette lands once in apply_theme at anim end.
    # Only re-apply the stylesheet when the accent actually changed in QSS
    # terms (e.g. static → dynamic). During consecutive dynamic transitions
    # the applied QSS already matches the from-color, so skip the re-parse.
    key, qss = _composed_qss(_theme_mode, c)
    if key != _applied_qss_key:
        app.setStyleSheet(qss)
        _applied_qss_key = key
        win = app.activeWindow()
        if win: win.update()
    for cb in _on_anim_tick:
        cb(c)
    if _anim_timer is None:
        _anim_timer = QTimer(app)
        _anim_timer.timeout.connect(_anim_tick)
    else:
        _anim_timer.stop()
    _anim_timer.start(_ANIM_MS)


def _anim_tick():
    global _anim_step, _dynamic_accent, _anim_timer, _anim_from, _anim_to
    _anim_step += 1
    t = _anim_step / _ANIM_STEPS
    t = 1.0 - (1.0 - t) ** 3
    r = int(_anim_from.red() + (_anim_to.red() - _anim_from.red()) * t)
    g = int(_anim_from.green() + (_anim_to.green() - _anim_from.green()) * t)
    b = int(_anim_from.blue() + (_anim_to.blue() - _anim_from.blue()) * t)
    color = QColor(r, g, b)
    _dynamic_accent = color
    ACCENTS["dynamic"] = color
    app = QApplication.instance()
    if app is None: return
    # No per-frame palette write: any effective app.setPalette() makes Qt
    # reset DWMWA_USE_IMMERSIVE_DARK_MODE (Mica flashes white mid-animation).
    # Subscribers repaint themselves via _on_anim_tick; the palette lands
    # once in apply_theme at the final tick.
    for cb in _on_anim_tick:
        cb(color)
    if _anim_step >= _ANIM_STEPS:
        _anim_timer.stop()
        _dynamic_accent = _anim_to
        apply_theme(app, _theme_mode, "dynamic")


def clear_dynamic_accent():
    """Revert to user's chosen static accent."""
    global _dynamic_accent, _accent_name, _pending_timer, _pending_color, _anim_timer
    if _pending_timer:
        _pending_timer.stop()
    if _anim_timer:
        _anim_timer.stop()
    _pending_color = None
    _dynamic_accent = None
    s = QSettings("VBPlayer", "VB Player")
    _accent_name = str(s.value("accent", "purple") or "purple")
    apply_theme(QApplication.instance(), _theme_mode, _accent_name)


def on_anim_tick(callback):
    """Register callback(color) called each animation tick — lightweight updates only."""
    _on_anim_tick.append(callback)

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
