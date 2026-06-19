"""Platform detection and factory — single import point for platform-specific code."""

import os
import sys
from dataclasses import dataclass

from PyQt6.QtGui import QFont

from audio_player.platform.base import (
    CapabilityMatrix, UIBehaviorPolicy,
    PlatformThemeTracker, PlatformNotifier,
)

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_PLATFORM = sys.platform
_IS_LINUX = _PLATFORM == "linux"
_IS_MACOS = _PLATFORM == "darwin"
_IS_WINDOWS = _PLATFORM == "win32"

# Detect Wayland on Linux
_IS_WAYLAND = False
if _IS_LINUX:
    _IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    if not _IS_WAYLAND:
        # Also check WAYLAND_DISPLAY
        _IS_WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY"))


# ---------------------------------------------------------------------------
# PlatformInfo — read-only singleton
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlatformInfo:
    name: str
    is_linux: bool
    is_macos: bool
    is_windows: bool
    is_wayland: bool
    capabilities: CapabilityMatrix
    policy: UIBehaviorPolicy


def _build_capabilities() -> CapabilityMatrix:
    """Build capability matrix for the current platform."""
    if _IS_MACOS:
        return CapabilityMatrix(
            supports_native_titlebar=True,
            supports_frameless_shadow=True,
            supports_native_fullscreen=True,
            supports_vibrancy=True,
            supports_system_accent=True,
            supports_system_dark_mode=True,
            supports_toast=True,
        )
    elif _IS_WINDOWS:
        return CapabilityMatrix(
            supports_frameless_shadow=True,
            supports_mica=True,
            supports_acrylic=True,
            supports_system_accent=True,
            supports_system_dark_mode=True,
            supports_toast=True,
            supports_dsd_native=True,
        )
    else:  # Linux
        return CapabilityMatrix(
            supports_app_indicator=not _IS_WAYLAND,
            supports_dbus_notifications=True,
            wayland_csd_fallback=_IS_WAYLAND,
        )


def _build_policy(caps: CapabilityMatrix) -> UIBehaviorPolicy:
    """Build UI behavior policy from capabilities."""
    if _IS_MACOS:
        return UIBehaviorPolicy(
            titlebar_style="native",
            material="vibrancy",
            font_family="SF Pro Display",
            font_size=13,
            system_accent_available=True,
            dark_titlebar_supported=True,
            notification_backend="usernotification",
            recommended_audio_sink="osxaudiosink",
        )
    elif _IS_WINDOWS:
        return UIBehaviorPolicy(
            titlebar_style="frameless",
            material="mica",
            font_family="Segoe UI Variable",
            font_size=10,
            system_accent_available=True,
            dark_titlebar_supported=True,
            notification_backend="toast",
            recommended_audio_sink="wasapi2sink",
        )
    else:  # Linux
        return UIBehaviorPolicy(
            titlebar_style="csd" if _IS_WAYLAND else "frameless",
            font_family="sans-serif",
            font_size=10,
            tray_backend="appindicator" if not _IS_WAYLAND else "qsystemtray",
            notification_backend="dbus",
            recommended_audio_sink="pipewiresink" if _IS_WAYLAND else "pulsesink",
        )


_caps = _build_capabilities()
_policy = _build_policy(_caps)

platform_info = PlatformInfo(
    name={"linux": "linux", "darwin": "macos", "win32": "windows"}.get(_PLATFORM, "unknown"),
    is_linux=_IS_LINUX,
    is_macos=_IS_MACOS,
    is_windows=_IS_WINDOWS,
    is_wayland=_IS_WAYLAND,
    capabilities=_caps,
    policy=_policy,
)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def get_system_font() -> QFont:
    """Return the recommended system font for the current platform."""
    font = QFont(platform_info.policy.font_family, platform_info.policy.font_size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def create_system_media_service(engine, controller, playlist, settings_ctrl, parent=None):
    """Create the platform-appropriate system media service."""
    if _IS_LINUX:
        from audio_player.player.mpris2 import Mpris2Service
        svc = Mpris2Service(engine, controller, playlist, parent)
        if hasattr(svc, 'raiseRequested'):
            return svc
        return svc
    elif _IS_MACOS:
        try:
            from audio_player.player.macos_media import MacOSSMediaService
            return MacOSSMediaService(engine, controller, parent)
        except ImportError:
            return None
    elif _IS_WINDOWS:
        try:
            from audio_player.player.smtc import SmtcService
            return SmtcService(engine, controller, parent)
        except ImportError:
            return None
    return None


def create_theme_tracker() -> PlatformThemeTracker | None:
    """Create the platform-appropriate theme tracker."""
    if not _caps.supports_system_dark_mode:
        return None
    try:
        if _IS_MACOS:
            from audio_player.platform.macos.theme import MacOSThemeTracker
            return MacOSThemeTracker()
        elif _IS_WINDOWS:
            from audio_player.platform.windows.theme import WinThemeTracker
            return WinThemeTracker()
        else:
            from audio_player.platform.linux.theme import LinuxThemeTracker
            return LinuxThemeTracker()
    except ImportError:
        return None


def create_notifier() -> PlatformNotifier | None:
    """Create the platform-appropriate notifier."""
    if _caps.supports_toast and _IS_WINDOWS:
        try:
            from audio_player.platform.windows.notifications import WinNotifier
            return WinNotifier()
        except ImportError:
            pass
    elif _caps.supports_toast and _IS_MACOS:
        try:
            from audio_player.platform.macos.notifications import MacOSNotifier
            return MacOSNotifier()
        except ImportError:
            pass
    elif _caps.supports_dbus_notifications:
        try:
            from audio_player.platform.linux.notifications import LinuxNotifier
            return LinuxNotifier()
        except ImportError:
            pass
    return None


def get_recommended_audio_sink() -> str:
    """Return the recommended GStreamer audio sink for this platform."""
    return platform_info.policy.recommended_audio_sink
