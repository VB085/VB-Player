"""KDE KWin blur-behind enabler — true frosted glass via _KDE_NET_WM_BLUR_BEHIND_REGION.

Uses ctypes to call Xlib directly. No extra deps needed — libX11 is always present on X11.
"""

import ctypes
import ctypes.util
from PyQt6.QtCore import QObject


# X11 atom types
XA_CARDINAL = 6
PropModeReplace = 0


class KWinBlurEnabler(QObject):
    """Enable/disable KWin blur behind a QWidget window on KDE Plasma (X11 only)."""

    def __init__(self, widget, parent=None):
        super().__init__(parent)
        self._widget = widget
        self._xlib = None
        self._display = None
        self._atom = None
        self._enabled = False

        # Only works on X11 — refuse on Wayland
        import os
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or \
           os.environ.get("WAYLAND_DISPLAY", ""):
            return

        lib_path = ctypes.util.find_library("X11")
        if not lib_path:
            return
        self._xlib = ctypes.CDLL(lib_path)

    def _ensure_display(self):
        if self._display is not None:
            return True
        if self._xlib is None:
            return False
        try:
            self._display = self._xlib.XOpenDisplay(None)
            if not self._display:
                return False
            self._atom = self._xlib.XInternAtom(
                self._display, b"_KDE_NET_WM_BLUR_BEHIND_REGION", False
            )
            return True
        except Exception:
            return False

    def enable(self):
        """Enable blur for the entire window."""
        if self._enabled:
            return
        if not self._ensure_display():
            return
        win_id = int(self._widget.winId())
        w = self._widget.width()
        h = self._widget.height()
        if w <= 0 or h <= 0:
            w, h = 1920, 1080  # reasonable default before first show
        data = (ctypes.c_uint32 * 4)(0, 0, w, h)
        self._xlib.XChangeProperty(
            self._display, win_id, self._atom, XA_CARDINAL, 32,
            PropModeReplace, ctypes.cast(data, ctypes.c_void_p), 4,
        )
        self._xlib.XFlush(self._display)
        self._enabled = True

    def update_rect(self):
        """Update blur region after resize (call from resizeEvent)."""
        if not self._enabled:
            return
        if not self._display:
            return
        win_id = int(self._widget.winId())
        w = self._widget.width()
        h = self._widget.height()
        data = (ctypes.c_uint32 * 4)(0, 0, w, h)
        self._xlib.XChangeProperty(
            self._display, win_id, self._atom, XA_CARDINAL, 32,
            PropModeReplace, ctypes.cast(data, ctypes.c_void_p), 4,
        )
        self._xlib.XFlush(self._display)

    def disable(self):
        """Remove blur property from window."""
        if not self._enabled:
            return
        if not self._display:
            return
        win_id = int(self._widget.winId())
        self._xlib.XDeleteProperty(self._display, win_id, self._atom)
        self._xlib.XFlush(self._display)
        self._enabled = False

    def cleanup(self):
        """Release X11 display connection."""
        self.disable()
        if self._display:
            self._xlib.XCloseDisplay(self._display)
            self._display = None
