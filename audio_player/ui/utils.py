"""Shared utility functions used across UI widgets."""

from audio_player.app import current_theme_mode


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
