"""Shared utility functions used across UI widgets."""

from PyQt6.QtCore import QSettings
from audio_player.app import current_theme_mode


def cover_radius_enabled() -> bool:
    s = QSettings("VBPlayer", "VB Player")
    return str(s.value("album_cover_radius", "true")).lower() == "true"


def cover_corner_radius() -> int:
    return 8 if cover_radius_enabled() else 0


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
