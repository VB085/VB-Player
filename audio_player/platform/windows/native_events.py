"""Windows native event handlers — Aero Snap, media keys, title-bar hit test.

Provides ``WindowsNativeMixin`` to be mixed into QMainWindow for:
- Aero Snap / drag-to-edge window snapping (WM_NCHITTEST)
- Multimedia keyboard key support (WM_APPCOMMAND)
- Proper caption area for frameless windows
"""

import sys
import ctypes
from ctypes import wintypes

# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------

WM_NCHITTEST = 0x0084
WM_APPCOMMAND = 0x0319
WM_NCCALCSIZE = 0x0083

HT_CAPTION = 2
HT_LEFT = 10
HT_RIGHT = 11
HT_TOP = 12
HT_TOPLEFT = 13
HT_TOPRIGHT = 14
HT_BOTTOM = 15
HT_BOTTOMLEFT = 16
HT_BOTTOMRIGHT = 17
HT_BORDER = 18

# AppCommand media keys
APPCOMMAND_MEDIA_PLAY_PAUSE = 14
APPCOMMAND_MEDIA_NEXT_TRACK = 11
APPCOMMAND_MEDIA_PREV_TRACK = 12
APPCOMMAND_MEDIA_STOP = 13
APPCOMMAND_VOLUME_UP = 10
APPCOMMAND_VOLUME_DOWN = 9

# GetWindowLong / SetWindowLong
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_OVERLAPPED = 0x00000000
WS_OVERLAPPEDWINDOW = (WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU |
                        WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)

TITLE_BAR_HEIGHT = 40  # height of our custom title bar
EDGE_MARGIN = 6  # same as frameless_resize.py


class WindowsNativeMixin:
    """Mixin for QMainWindow — Windows native events for frameless window.

    Usage::

        class MainWindow(WindowsNativeMixin, FramelessResizeMixin, QMainWindow):
            def __init__(self):
                super().__init__()
                # Must call .setup_native() after windowHandle() is available
    """

    def _init_native_events(self):
        """Call once after window is shown (HWND available)."""
        if sys.platform != "win32":
            return

        # Install native event filter for WM_NCHITTEST and WM_APPCOMMAND
        try:
            self.windowHandle().installEventFilter(self)
        except Exception:
            pass

    def nativeEvent(self, eventType, message):
        """Handle Windows native events — NCHITTEST and APPCOMMAND."""
        if sys.platform != "win32":
            return False, None

        try:
            msg_ptr = int(message)
        except (TypeError, ValueError):
            return False, None

        if not msg_ptr:
            return False, None

        # MSG structure: HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam
        msg_id = ctypes.c_uint32.from_address(msg_ptr + 8).value

        if msg_id == WM_NCHITTEST:
            return self._handle_nchittest(msg_ptr)
        elif msg_id == WM_APPCOMMAND:
            return self._handle_appcommand(msg_ptr)

        return False, None

    def _handle_nchittest(self, msg_ptr):
        """Handle WM_NCHITTEST — enable Aero Snap for frameless windows."""
        try:
            # MSG layout (x64): hwnd@0, msg@8, wParam@16, lParam@24
            lParam = ctypes.c_int64.from_address(msg_ptr + 24).value
            x = lParam & 0xFFFF
            y = (lParam >> 16) & 0xFFFF

            # Convert to window-local coords
            hwnd = int(self.winId())
            pt = wintypes.POINT(x, y)
            ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(pt))

            # Get window dimensions
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            px, py = pt.x, pt.y

            # Title bar area → caption (allows drag-to-snap)
            if py >= 0 and py <= TITLE_BAR_HEIGHT:
                # But not on buttons — those should get regular mouse events
                # Right-aligned buttons area: skip caption
                btn_area_start = w - 160  # approximate button area
                if px < btn_area_start or px > w:
                    return True, HT_CAPTION

            # Edge areas for resize
            left = px <= EDGE_MARGIN
            right = px >= w - EDGE_MARGIN
            top = py <= EDGE_MARGIN
            bottom = py >= h - EDGE_MARGIN

            if top and left:       return True, HT_TOPLEFT
            if top and right:      return True, HT_TOPRIGHT
            if bottom and left:    return True, HT_BOTTOMLEFT
            if bottom and right:   return True, HT_BOTTOMRIGHT
            if left:               return True, HT_LEFT
            if right:              return True, HT_RIGHT
            if top:                return True, HT_TOP
            if bottom:             return True, HT_BOTTOM

            # Top border (thin strip above title) for window drag
            if py <= 4 and px >= 0 and px <= w:
                return True, HT_CAPTION

        except Exception:
            pass

        return False, None

    def _handle_appcommand(self, msg_ptr):
        """Handle WM_APPCOMMAND — multimedia keyboard keys."""
        try:
            # MSG layout (x64): hwnd@0, msg@8, wParam@16, lParam@24
            wParam = ctypes.c_uint64.from_address(msg_ptr + 16).value
            cmd = (wParam >> 16) & 0xFFFF

            if cmd == APPCOMMAND_MEDIA_PLAY_PAUSE:
                self._on_media_key("play_pause")
                return True, 1
            elif cmd == APPCOMMAND_MEDIA_NEXT_TRACK:
                self._on_media_key("next")
                return True, 1
            elif cmd == APPCOMMAND_MEDIA_PREV_TRACK:
                self._on_media_key("prev")
                return True, 1
            elif cmd == APPCOMMAND_MEDIA_STOP:
                self._on_media_key("stop")
                return True, 1
        except Exception:
            pass

        return False, None

    def _on_media_key(self, action: str):
        """Dispatch media key to main window handler. Override in MainWindow."""
        pass
