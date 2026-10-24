"""Windows DWM materials — Mica, Acrylic, Dark Mode title bar.

Uses ``DwmSetWindowAttribute`` via ctypes to apply native Windows 11 materials.
"""

import ctypes
from ctypes import wintypes
import sys

HRESULT = getattr(wintypes, 'HRESULT', wintypes.LONG)  # MSYS2 compat

# ---------------------------------------------------------------------------
# DWM API
# ---------------------------------------------------------------------------

_dwm = ctypes.windll.dwmapi

# DwmSetWindowAttribute
_DwmSetWindowAttribute = _dwm.DwmSetWindowAttribute
_DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD]
_DwmSetWindowAttribute.restype = HRESULT

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


def system_backdrop_available() -> bool:
    """Win11 22H2+ can composite Mica/Acrylic behind a transparent client area
    via DWMWA_SYSTEMBACKDROP_TYPE. Earlier builds cannot."""
    return sys.platform == "win32" and _is_win11_22h2()


def native_rounded_corners() -> bool:
    """Win11 rounds window corners in DWM — no client-side mask needed."""
    return sys.platform == "win32" and _is_win11()


def frame_inset(hwnd: int) -> tuple:
    """Return (dx, dy) between the window rect and the client rect.

    (0, 0) means the client area covers the whole window (frameless /
    NCCALCSIZE-subclass working). Non-zero means the native frame is
    showing — the Win7-border failure symptom.
    """
    class _RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_int64
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    wr, cr = _RECT(), _RECT()
    h = wintypes.HWND(hwnd)
    if not user32.GetWindowRect(h, ctypes.byref(wr)):
        return (0, 0)
    if not user32.GetClientRect(h, ctypes.byref(cr)):
        return (0, 0)
    return ((wr.r - wr.l) - (cr.r - cr.l), (wr.b - wr.t) - (cr.b - cr.t))


def dark_mode_flag(hwnd: int):
    """Read DWMWA_USE_IMMERSIVE_DARK_MODE; None if unreadable."""
    val = wintypes.DWORD(0)
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
        ctypes.byref(val), ctypes.sizeof(val))
    return val.value if hr == 0 else None


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


def apply_rounded_corners(hwnd: int, pref: str = "round") -> bool:
    """Apply Windows 11 rounded corner preference.

    *pref*: "round" (8px), "small" (4px) or "none" (square).
    """
    p = {"none": _DWMCP_DONOTROUND, "small": _DWMCP_ROUNDSMALL}.get(pref, _DWMCP_ROUND)
    return _set_dwm_dword(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, p)


_DWMNCRP_DISABLED = 2  # DWMWA_NCRENDERING_POLICY value: never draw the NC frame

_GWL_STYLE = -16
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_SWP_FRAMECHANGED = 0x0020


def set_window_frame(hwnd: int, caption: bool) -> bool:
    """Add/remove WS_CAPTION|WS_THICKFRAME from a frameless window.

    After a fullscreen round-trip returning to MAXIMIZED, DWM composites a
    caption-bar overlay (~45px light band) over windows that still carry
    WS_CAPTION — even with a WM_NCCALCSIZE subclass eating the frame
    (geometry stays inset-0, so rect probes can't see it). Maximized
    windows don't need caption/thickframe at all, so strip them there.
    """
    h = wintypes.HWND(hwnd)
    style = _user32.GetWindowLongPtrW(h, _GWL_STYLE)
    mask = _WS_CAPTION | _WS_THICKFRAME
    new_style = (style | mask) if caption else (style & ~mask)
    if new_style == style:
        return True
    _user32.SetWindowLongPtrW(h, _GWL_STYLE, new_style)
    # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
    _user32.SetWindowPos(h, None, 0, 0, 0, 0, _SWP_FRAMECHANGED | 0x1 | 0x2 | 0x4 | 0x10)
    return True


def disable_nc_rendering(hwnd: int) -> bool:
    """Stop DWM from compositing the native frame OVER the client area.

    With WS_OVERLAPPEDWINDOW + a WM_NCCALCSIZE subclass returning 0, the
    client covers the whole window geometrically — but after fullscreen
    round-trips DWM can still draw the caption bar as a compositor overlay
    (invisible to GetWindowRect/GetClientRect, ~45px at the top). We paint
    everything ourselves, so NC rendering must stay off.
    """
    return _set_dwm_dword(hwnd, DWMWA_NCRENDERING_POLICY, _DWMNCRP_DISABLED)


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


# ---------------------------------------------------------------------------
# DWM Frame Extension — enables system animations for frameless windows
# ---------------------------------------------------------------------------

# Per-process: one WNDPROC callback is enough (shared by all subclassed windows)
_WNDPROC_CB = ctypes.WINFUNCTYPE(
    ctypes.c_int64,
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
    wintypes.LPARAM, ctypes.c_uint64, ctypes.c_uint64,
)

_user32 = ctypes.windll.user32
_comctl32 = ctypes.windll.comctl32
# Set correct argtypes for 64-bit — ctypes defaults to 32-bit int otherwise
_comctl32.SetWindowSubclass.argtypes = [
    wintypes.HWND, _WNDPROC_CB, ctypes.c_uint64, ctypes.c_uint64,
]
_comctl32.SetWindowSubclass.restype = wintypes.BOOL
_comctl32.DefSubclassProc.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
]
_comctl32.DefSubclassProc.restype = ctypes.c_int64

@_WNDPROC_CB
def _nccalcsize_subclass(hwnd, msg, wp, lp, uid, ref):
    """Tell DWM: entire window is client area, no non-client borders."""
    if msg == 0x0083 and wp == 1:  # WM_NCCALCSIZE, wParam=TRUE
        return 0
    return _comctl32.DefSubclassProc(hwnd, msg, wp, lp)

_FRAME_DONE = set()  # track HWNDs that already have frame enabled


def enable_dwm_frame(hwnd: int, force: bool = False) -> bool:
    """Enable DWM system animations for a frameless window.

    Adds WS_OVERLAPPEDWINDOW style, enables DWM transitions, and installs
    a WM_NCCALCSIZE subclass to suppress the native title bar. Call once
    after the window HWND is valid (e.g. in showEvent). Pass *force* to
    re-apply after Qt rewrote the window style (fullscreen round-trips
    silently wipe the style bits and DWM attributes).
    """
    if hwnd in _FRAME_DONE and not force:
        return True

    try:
        h = wintypes.HWND(hwnd)

        # 1. Add WS_OVERLAPPEDWINDOW — tells DWM to animate this window
        GWL_STYLE = -16
        WS_OVERLAPPEDWINDOW = 0x00CF0000
        _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.GetWindowLongPtrW.restype = ctypes.c_int64
        _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int64]
        _user32.SetWindowLongPtrW.restype = ctypes.c_int64
        style = _user32.GetWindowLongPtrW(h, GWL_STYLE)
        _user32.SetWindowLongPtrW(h, GWL_STYLE, style | WS_OVERLAPPEDWINDOW)

        # 2. Enable DWM transitions (disable forced-disable)
        DWMWA_TRANSITIONS_FORCEDISABLED = 26
        val = wintypes.BOOL(False)
        _DwmSetWindowAttribute(h, DWMWA_TRANSITIONS_FORCEDISABLED,
                               ctypes.byref(val), ctypes.sizeof(val))

        # 3. Subclass WM_NCCALCSIZE to remove native borders
        _comctl32.SetWindowSubclass(h, _nccalcsize_subclass, 1, 0)

        # 4. Kill DWM's own NC frame drawing — after fullscreen round-trips
        # it draws the caption bar as an overlay over the client area
        # (geometry-invisible; seen as a "Win7 title bar")
        _set_dwm_dword(hwnd, DWMWA_NCRENDERING_POLICY, _DWMNCRP_DISABLED)

        # 5. Extend DWM frame into entire client area
        class MARGINS(ctypes.Structure):
            _fields_ = [('left', wintypes.INT), ('right', wintypes.INT),
                       ('top', wintypes.INT), ('bottom', wintypes.INT)]
        margins = MARGINS(0, 0, 0, 1)
        _dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(MARGINS)]
        _dwm.DwmExtendFrameIntoClientArea.restype = HRESULT
        _dwm.DwmExtendFrameIntoClientArea(h, ctypes.byref(margins))

        # 6. Force frame recalculation
        SWP_FLAGS = 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010
        _user32.SetWindowPos(h, None, 0, 0, 0, 0, SWP_FLAGS)

        _FRAME_DONE.add(hwnd)
        return True
    except Exception as e:
        import sys as _sys
        print(f"[dwm] enable_dwm_frame failed: {e}", file=_sys.stderr)
        return False
