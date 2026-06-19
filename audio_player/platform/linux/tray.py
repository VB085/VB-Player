"""Linux tray — tries AppIndicator, falls back to QSystemTrayIcon."""

from PyQt6.QtWidgets import QSystemTrayIcon


def create_tray_icon(parent=None) -> QSystemTrayIcon | None:
    """Create a tray icon. On Linux, tries AppIndicator first."""
    try:
        import gi
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3
        # AppIndicator3 is available — but Qt integration requires
        # additional work. For now, use QSystemTrayIcon.
    except (ImportError, ValueError):
        pass

    return QSystemTrayIcon(parent) if QSystemTrayIcon.isSystemTrayAvailable() else None
