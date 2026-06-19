"""Platform abstraction — data classes and abstract interfaces.

CapabilityMatrix describes what a platform *can* do (boolean capabilities).
UIBehaviorPolicy describes what we *will* do (decisions derived from capabilities).
"""

from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont


# ---------------------------------------------------------------------------
# CapabilityMatrix — "can this platform do X?"
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityMatrix:
    """Read-only platform capabilities. Query instead of checking sys.platform."""

    # Window
    supports_native_titlebar: bool = False
    supports_frameless_shadow: bool = False
    supports_native_fullscreen: bool = False

    # Materials
    supports_vibrancy: bool = False
    supports_mica: bool = False
    supports_acrylic: bool = False

    # Theming
    supports_system_accent: bool = False
    supports_system_dark_mode: bool = False

    # System tray
    supports_app_indicator: bool = False
    supports_qsystem_tray: bool = True

    # Notifications
    supports_toast: bool = False
    supports_dbus_notifications: bool = False

    # Display server
    wayland_csd_fallback: bool = False

    # Audio
    supports_dsd_native: bool = False


# ---------------------------------------------------------------------------
# UIBehaviorPolicy — "what will we do on this platform?"
# ---------------------------------------------------------------------------

@dataclass
class UIBehaviorPolicy:
    """Decisions for UI behavior derived from capabilities + user preferences."""

    # Titlebar
    titlebar_style: str = "frameless"   # "native" | "frameless" | "csd"

    # Material effect
    material: str = "none"              # "vibrancy" | "mica" | "acrylic" | "none"

    # Font
    font_family: str = "sans-serif"
    font_size: int = 10

    # Theming
    system_accent_available: bool = False
    dark_titlebar_supported: bool = False

    # Tray
    tray_backend: str = "qsystemtray"   # "appindicator" | "qsystemtray"

    # Notifications
    notification_backend: str = "none"  # "dbus" | "usernotification" | "toast" | "none"

    # File dialog
    use_native_dialog: bool = True

    # Audio
    recommended_audio_sink: str = "autoaudiosink"


# ---------------------------------------------------------------------------
# Abstract platform interfaces
# ---------------------------------------------------------------------------

class PlatformThemeTracker(QObject):
    """Tracks system theme changes (dark/light, accent color)."""

    systemThemeChanged = pyqtSignal(str)      # "dark" | "light"
    systemAccentChanged = pyqtSignal(QColor)  # new accent color

    def start_tracking(self):
        """Begin monitoring system theme changes."""
        pass

    def stop(self):
        """Stop monitoring."""
        pass

    def current_system_theme(self) -> str:
        """Return current system theme: 'dark' or 'light'."""
        return "dark"

    def current_system_accent(self) -> QColor | None:
        """Return current system accent color, or None if not supported."""
        return None


class PlatformNotifier(QObject):
    """Sends native OS notifications."""

    notificationClicked = pyqtSignal()

    def show(self, title: str, body: str):
        """Show a native notification."""
        pass

    def is_authorized(self) -> bool:
        """Check if the app has permission to send notifications."""
        return True

    def request_authorization(self):
        """Request notification permission from the user."""
        pass
