"""Windows DWM materials — Mica, Acrylic, Dark Mode title bar.

Uses ``DwmSetWindowAttribute`` via ctypes to apply native Windows 11 materials.
"""

import ctypes
from ctypes import wintypes
import sys

# ---------------------------------------------------------------------------
# DWM API
# ---------------------------------------------------------------------------

_dwm = ctypes.windll.dwmapi

# DwmSetWindowAttribute
_DwmSetWindowAttribute = _dwm.DwmSetWindowAttribute
_DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD]
_DwmSetWindowAttribute.restype = wintypes.HRESULT

# Window attributes
DWMWA_USE_IMMERSIVE_DARK_MODE = 20          # Win10 20H1+
DWMWA_SYSTEMBACKDROP_TYPE = 38               # Win11 22H2+
DWMWA_MICA = 1029                            # Win11 21H2 (deprecated)
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_WINDOW_CORNER_PREFERENCE = 33          # Win11
DWMWA_NCRENDERING_POLICY = 2
DWMWA_NCRENDERING_ENABLED = 1

# SystemBackdropType enum
_DWMSBT_AUTO = 0
_DWMSBT_NONE = 1
_DWMSBT_MAINWINDOW = 2    # Mica
_DWMSBT_TRANSIENTWINDOW = 3  # Mica Alt (stronger tint)
_DWMSBT_TABBEDWINDOW = 4  # Acrylic

# Corner preference
_DWMCP_DEFAULT = 0
_DWMCP_DONOTROUND = 1
_DWMCP_ROUND = 2
_DWMCP_ROUNDSMALL = 3

# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def _is_win11() -> bool:
    """Check if running Windows 11 (build >= 22000)."""
    v = sys.getwindowsversion()
    return v.major >= 10 and v.build >= 22000


def _is_win11_22h2() -> bool:
    """Check if running Windows 11 22H2+ (build >= 22621)."""
    v = sys.getwindowsversion()
    return v.major >= 10 and v.build >= 22621


def _set_dwm_bool(hwnd: int, attr: int, value: bool) -> bool:
    """Set a DWM boolean attribute. Returns True on success."""
    val = wintypes.BOOL(value)
    hr = _DwmSetWindowAttribute(wintypes.HWND(hwnd), attr,
                                 ctypes.byref(val), ctypes.sizeof(val))
    return hr >= 0


def _set_dwm_dword(hwnd: int, attr: int, value: int) -> bool:
    """Set a DWM DWORD attribute. Returns True on success."""
    val = wintypes.DWORD(value)
    hr = _DwmSetWindowAttribute(wintypes.HWND(hwnd), attr,
                                 ctypes.byref(val), ctypes.sizeof(val))
    return hr >= 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_dark_titlebar(hwnd: int) -> bool:
    """Apply Windows dark-mode title bar (black caption bar, white caption text)."""
    return _set_dwm_bool(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, True)


def apply_light_titlebar(hwnd: int) -> bool:
    """Apply Windows light-mode title bar."""
    return _set_dwm_bool(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, False)


def apply_mica(hwnd: int) -> bool:
    """Apply Windows 11 Mica backdrop.

    Mica samples the desktop wallpaper once and produces a translucent,
    tinted backdrop. Best for long-lived windows.
    """
    if not _is_win11():
        return False
    # Try new API first (Win11 22H2+)
    if _is_win11_22h2():
        if _set_dwm_dword(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_MAINWINDOW):
            return True
    # Fallback: Win11 21H2
    return _set_dwm_bool(hwnd, DWMWA_MICA, True)


def apply_mica_alt(hwnd: int) -> bool:
    """Apply Windows 11 Mica Alt backdrop (stronger tint).

    Uses the user's desktop background more prominently.
    """
    if _is_win11_22h2():
        return _set_dwm_dword(hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                              _DWMSBT_TRANSIENTWINDOW)
    return apply_mica(hwnd)


def apply_acrylic(hwnd: int) -> bool:
    """Apply Windows 11 Acrylic backdrop (blurred, translucent).

    Acrylic is most vibrant and responsive — updates in real time
    with content behind the window. Best for transient surfaces.
    """
    if _is_win11_22h2():
        return _set_dwm_dword(hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                              _DWMSBT_TABBEDWINDOW)
    # Pre-Win11 22H2: Mica is closest available
    return apply_mica(hwnd)


def clear_backdrop(hwnd: int) -> bool:
    """Remove any DWM backdrop effect."""
    if _is_win11_22h2():
        return _set_dwm_dword(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_NONE)
    return _set_dwm_bool(hwnd, DWMWA_MICA, False)


def apply_rounded_corners(hwnd: int) -> bool:
    """Apply Windows 11 rounded corner preference."""
    return _set_dwm_dword(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, _DWMCP_ROUND)


def apply_border_color(hwnd: int, r: int, g: int, b: int) -> bool:
    """Set the window border color (Windows 11). *r*, *g*, *b* in 0-255."""
    color = (b << 16) | (g << 8) | r  # COLORREF: 0xBBGGRR (no alpha)
    return _set_dwm_dword(hwnd, DWMWA_BORDER_COLOR, color)


def apply_titlebar_color(hwnd: int, r: int, g: int, b: int) -> bool:
    """Set the title bar background color."""
    color = (b << 16) | (g << 8) | r
    return _set_dwm_dword(hwnd, DWMWA_CAPTION_COLOR, color)


def enable_dark_mode_for_window(hwnd: int) -> bool:
    """Full dark-mode treatment: dark title bar + dark context menus."""
    ok = apply_dark_titlebar(hwnd)
    # Set dark border on Win11
    if _is_win11():
        apply_border_color(hwnd, 40, 40, 40)
    return ok
