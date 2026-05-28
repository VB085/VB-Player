"""Centralized theme colors and style helpers.

Single source of truth for all theme/accent color values.
Phase 1 of QSS migration — replaces scattered is_light ternaries.
"""

from audio_player.app import current_accent, current_theme_mode


# ── Color palettes ──────────────────────────────────────────────

DARK_COLORS = {
    "muted": "#94a3b8",
    "text": "#e2e8f0",
    "sub": "#64748b",
    "cover_bg": "#141414",
    "surface": "#0f0f0f",
    "border": "#1a1a1a",
    "hover_bg": "#1a1a2e",
    "card_bg": "#141418",
    "separator": "#141414",
    "name": "#e2e8f0",
    "artist": "#94a3b8",
}

LIGHT_COLORS = {
    "muted": "#666666",
    "text": "#333333",
    "sub": "#888888",
    "cover_bg": "#e0e0e0",
    "surface": "#f0f0f0",
    "border": "#e0e0e0",
    "hover_bg": "#e0e0e0",
    "card_bg": "#f0f0f0",
    "separator": "#d0d0d0",
    "name": "#333333",
    "artist": "#666666",
}


def theme_colors(is_light: bool | None = None) -> dict:
    """Return the color dict for the current or specified theme."""
    if is_light is None:
        is_light = current_theme_mode() == "light"
    return LIGHT_COLORS if is_light else DARK_COLORS


def accent_colors() -> dict:
    """Return accent-derived color values."""
    a = current_accent()
    return {
        "base": a.name(),
        "light": a.lighter(130).name(),
        "dark": a.darker(120).name(),
        "hover": a.lighter(115).name(),
        "highlight": a.lighter(160).name(),
        "nav_bg": a.darker(160).name(),
        "nav_hover_bg": a.darker(140).name(),
    }


# ── Style templates ────────────────────────────────────────────

MENU_STYLE_TEMPLATE = (
    "QMenu{{background:#0f0f0f;color:#d0d0d0;border:1px solid #222;"
    "border-radius:6px;padding:4px;}}"
    "QMenu::item{{padding:5px 28px 5px 14px;border-radius:3px;}}"
    "QMenu::item:selected{{background:{accent}33;}}"
    "QMenu::separator{{height:1px;background:#222;margin:4px 8px;}}"
)

MENU_STYLE_LIGHT_TEMPLATE = (
    "QMenu{{background:#ffffff;color:#333333;border:1px solid #d0d0d0;"
    "border-radius:6px;padding:4px;}}"
    "QMenu::item{{padding:5px 28px 5px 14px;border-radius:3px;}}"
    "QMenu::item:selected{{background:{accent}22;}}"
    "QMenu::separator{{height:1px;background:#e0e0e0;margin:4px 8px;}}"
)


def menu_style(accent_hex: str | None = None) -> str:
    """Return the context menu QSS for the current theme."""
    if accent_hex is None:
        accent_hex = current_accent().name()
    is_light = current_theme_mode() == "light"
    tpl = MENU_STYLE_LIGHT_TEMPLATE if is_light else MENU_STYLE_TEMPLATE
    return tpl.format(accent=accent_hex)


def accent_button_style(accent_hex: str | None = None, hover_hex: str | None = None) -> str:
    """Standard accent button: filled background, white text."""
    if accent_hex is None:
        accent_hex = current_accent().name()
    if hover_hex is None:
        hover_hex = current_accent().lighter(115).name()
    return (
        f"QPushButton{{background:{accent_hex};color:#fff;border:none;"
        f"border-radius:5px;padding:5px 12px;font-size:11px;}}"
        f"QPushButton:hover{{background:{hover_hex};}}"
    )


def transparent_button_style(text_color: str, hover_bg: str, hover_color: str) -> str:
    """Transparent button with hover effect (back, edit, etc.)."""
    return (
        f"QPushButton{{background:transparent;color:{text_color};border:none;"
        f"font-size:12px;padding:6px 12px;border-radius:4px;}}"
        f"QPushButton:hover{{background:{hover_bg};color:{hover_color};}}"
    )


def section_header_style(muted: str | None = None) -> str:
    """Section header label (track list, album track list, etc.)."""
    if muted is None:
        muted = theme_colors()["muted"]
    return (
        f"color:{muted};font-size:10px;font-weight:bold;"
        f"letter-spacing:2px;"
    )


def meta_chip_style(is_light: bool | None = None) -> str:
    """Metadata chip label (year, duration, format, etc.)."""
    c = theme_colors(is_light)
    bg = "#f0f0f0" if (is_light if is_light is not None else current_theme_mode() == "light") else "#141418"
    return f"background:{bg};color:{c['muted']};font-size:10px;padding:3px 8px;border-radius:3px;"


# ── ScrollArea transparent (commonly reused) ──────────────────

SCROLLAREA_TRANSPARENT = "QScrollArea{background:transparent;border:none;}"
