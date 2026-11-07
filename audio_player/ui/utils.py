"""Shared utility functions used across UI widgets."""

from PyQt6.QtCore import QSettings
from audio_player.app import current_theme_mode

_cached_cover_radius: int | None = None


def cover_radius_enabled() -> bool:
    return cover_corner_radius() > 0


def cover_corner_radius() -> int:
    global _cached_cover_radius
    if _cached_cover_radius is not None:
        return _cached_cover_radius
    try:
        s = QSettings("VBPlayer", "VB Player")
        enabled = str(s.value("album_cover_radius", "true")).lower() == "true"
        _cached_cover_radius = 8 if enabled else 0
    except Exception:
        _cached_cover_radius = 8
    return _cached_cover_radius


def refresh_cover_radius_cache():
    """Invalidate cached cover radius — call on settings change."""
    global _cached_cover_radius
    _cached_cover_radius = None


def format_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS, M:SS, or --:--."""
    if seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def is_light_mode() -> bool:
    """Return True when the current theme mode is 'light'."""
    return current_theme_mode() == "light"
