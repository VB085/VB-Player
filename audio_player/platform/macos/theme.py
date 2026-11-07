"""macOS theme tracker -- follows system appearance via NSUserDefaults.

Detects dark/light mode via AppleInterfaceStyle and accent color via
AppleAccentColor.  Uses a lightweight QTimer poll (3 s, same cadence as
the Linux and Windows trackers) supplemented by an NSNotificationCenter
observer for instant detection of theme changes.
"""

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor

from audio_player.platform.base import PlatformThemeTracker

_HAS_OBJC = False
if sys.platform == "darwin":
    try:
        import Foundation
        import AppKit
        _HAS_OBJC = True
    except ImportError:
        pass

# macOS accent-color index -> QColor  (System Preferences > General > Accent color)
_ACCENT_MAP: dict[int, QColor] = {
    -1: QColor("#007AFF"),   # Blue (default)
    0:  QColor("#FF375F"),   # Red
    1:  QColor("#FF9500"),   # Orange
    2:  QColor("#FFCC00"),   # Yellow
    3:  QColor("#34C759"),   # Green
    4:  QColor("#007AFF"),   # Blue
    5:  QColor("#5856D6"),   # Purple
    6:  QColor("#FF2D55"),   # Pink
    7:  QColor("#8E8E93"),   # Graphite
}


class MacOSThemeTracker(PlatformThemeTracker):
    """Tracks macOS system theme (dark/light) and accent color.

    Two detection paths:
    1. NSNotificationCenter observer on AppleInterfaceThemeChangedNotification
       for instant callbacks.
    2. QTimer poll (3 s) as a safety net -- catches changes the notification
       might miss (e.g. accent color changes without a theme flip).
    """

    _POLL_MS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_theme = "dark"
        self._current_accent: QColor | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._POLL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._observer = None

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def start_tracking(self):
        if not _HAS_OBJC:
            return
        self._poll()  # read initial values immediately
        self._poll_timer.start()
        # Register for instant theme-change notifications
        try:
            workspace_nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
            self._observer = workspace_nc.addObserverForName_object_queue_(
                "AppleInterfaceThemeChangedNotification",
                None,
                None,
                self._on_theme_notification,
            )
        except Exception:
            pass

    def stop(self):
        self._poll_timer.stop()
        if self._observer is not None:
            try:
                Foundation.NSNotificationCenter.defaultCenter().removeObserver_(self._observer)
            except Exception:
                pass
            self._observer = None

    def current_system_theme(self) -> str:
        return self._current_theme

    def current_system_accent(self) -> QColor | None:
        return self._current_accent

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    def _on_theme_notification(self, _notification):
        """Called by NSNotificationCenter when the system theme flips."""
        self._poll()

    def _poll(self):
        if not _HAS_OBJC:
            return
        theme = self._current_theme
        accent = self._current_accent
        try:
            defaults = Foundation.NSUserDefaults.standardUserDefaults()
            style = defaults.stringForKey_("AppleInterfaceStyle") or ""
            theme = "dark" if style.lower() == "dark" else "light"

            accent_idx = defaults.integerForKey_("AppleAccentColor")
            accent = _ACCENT_MAP.get(accent_idx, _ACCENT_MAP[-1])
        except Exception:
            pass

        if theme != self._current_theme:
            self._current_theme = theme
            self.systemThemeChanged.emit(theme)
        if accent and accent != self._current_accent:
            self._current_accent = accent
            self.systemAccentChanged.emit(accent)
