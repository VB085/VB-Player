"""Linux theme tracker — follows system appearance via gsettings (GNOME/KDE)."""

import subprocess

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor

from audio_player.platform.base import PlatformThemeTracker


class LinuxThemeTracker(PlatformThemeTracker):
    """Tracks GNOME/KDE system theme and accent via gsettings."""

    _GNOME_ACCENTS = {
        "blue":    QColor("#3584e4"),
        "teal":    QColor("#2190a4"),
        "green":   QColor("#3a944a"),
        "yellow":  QColor("#c7a000"),
        "orange":  QColor("#ed8b00"),
        "red":     QColor("#e62d42"),
        "pink":    QColor("#d5619a"),
        "purple":  QColor("#9141ac"),
        "slate":   QColor("#6f80a3"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_theme = "dark"
        self._current_accent: QColor | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._poll)

    @staticmethod
    def _gsettings_get(schema: str, key: str) -> str:
        try:
            r = subprocess.run(
                ["gsettings", "get", schema, key],
                capture_output=True, text=True, timeout=2,
            )
            return r.stdout.strip().strip("'\"")
        except Exception:
            return ""

    def start_tracking(self):
        self._poll()
        self._poll_timer.start()

    def stop(self):
        self._poll_timer.stop()

    def _poll(self):
        """Read system preferences and emit if changed. gsettings is fast (<1ms)."""
        theme = self._current_theme
        accent = self._current_accent
        try:
            scheme = self._gsettings_get(
                "org.gnome.desktop.interface", "color-scheme")
            if "dark" in scheme.lower():
                theme = "dark"
            elif scheme:
                theme = "light"

            accent_slug = self._gsettings_get(
                "org.gnome.desktop.interface", "accent-color")
            accent = self._GNOME_ACCENTS.get(accent_slug) or accent
        except Exception:
            pass

        if theme != self._current_theme:
            self._current_theme = theme
            self.systemThemeChanged.emit(theme)
        if accent and accent != self._current_accent:
            self._current_accent = accent
            self.systemAccentChanged.emit(accent)

    def current_system_theme(self) -> str:
        return self._current_theme

    def current_system_accent(self) -> QColor | None:
        return self._current_accent
