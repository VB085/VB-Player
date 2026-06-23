"""Windows theme tracker — follows system dark/light and accent color.

Reads Windows registry for initial values and polls for changes.
Also connects to Qt's built-in QStyleHints.colorSchemeChanged signal.
"""

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QApplication

from audio_player.platform.base import PlatformThemeTracker


class WinThemeTracker(PlatformThemeTracker):
    """Tracks Windows system theme (dark/light) and accent color.

    Dark/light is detected via both:
      - Registry: AppsUseLightTheme / SystemUsesLightTheme
      - Qt signal: QStyleHints.colorSchemeChanged (instant)

    Accent color is read from the DWM AccentColor registry key.
    """

    # Poll interval matches Linux tracker (3s); registry reads are cheap
    _POLL_MS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_theme = "dark"
        self._current_accent: QColor | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._POLL_MS)
        self._poll_timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_tracking(self):
        """Begin monitoring system theme changes."""
        self._poll()  # read initial values immediately
        self._poll_timer.start()

        # Qt signals on color-scheme change (instant, no polling needed)
        app = QApplication.instance()
        if app:
            app.styleHints().colorSchemeChanged.connect(self._on_qt_color_scheme)

    def stop(self):
        """Stop monitoring."""
        self._poll_timer.stop()

    def current_system_theme(self) -> str:
        """Return current system theme: 'dark' or 'light'."""
        return self._current_theme

    def current_system_accent(self) -> QColor | None:
        """Return current system accent color, or None if unavailable."""
        return self._current_accent

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_qt_color_scheme(self):
        """Qt detected a color-scheme change — re-read immediately."""
        self._poll()

    def _poll(self):
        """Read system preferences and emit if changed."""
        theme = self._current_theme
        accent = self._current_accent

        try:
            light = self._read_registry_dword(
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                "AppsUseLightTheme",
            )
            if light is not None:
                theme = "light" if light == 1 else "dark"

            color_dword = self._read_registry_dword(
                r"HKCU\Software\Microsoft\Windows\DWM",
                "AccentColor",
            )
            if color_dword is not None and color_dword != 0:
                # DWM AccentColor is AABBGGRR
                a = (color_dword >> 24) & 0xFF
                r = (color_dword >> 16) & 0xFF
                g = (color_dword >> 8) & 0xFF
                b = color_dword & 0xFF
                accent = QColor(r, g, b, a)
        except Exception:
            pass

        if theme != self._current_theme:
            self._current_theme = theme
            self.systemThemeChanged.emit(theme)
        if accent and accent != self._current_accent:
            self._current_accent = accent
            self.systemAccentChanged.emit(accent)

    @staticmethod
    def _read_registry_dword(key_path: str, value_name: str) -> int | None:
        """Read a DWORD value from the Windows registry. Returns None on failure."""
        import winreg
        try:
            hive_map = {
                "HKCU": winreg.HKEY_CURRENT_USER,
                "HKLM": winreg.HKEY_LOCAL_MACHINE,
            }
            hive_str, rest = key_path.split("\\", 1)
            hive = hive_map.get(hive_str, winreg.HKEY_CURRENT_USER)
            with winreg.OpenKey(hive, rest) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                return value
        except Exception:
            return None
