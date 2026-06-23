"""Windows taskbar integration — thumbnail toolbar buttons + progress bar.

Uses ``ITaskbarList3`` COM interface via ctypes. No Qt/WinRT dependency.
"""

import ctypes
import struct
from ctypes import wintypes


# ---------------------------------------------------------------------------
# COM boilerplate
# ---------------------------------------------------------------------------

def _pack_guid(d1, d2, d3, d4):
    return struct.pack('<IHH8B', d1, d2, d3, *d4)


class _COM:
    """Minimal COM helper."""

    def __init__(self, clsid: bytes, iid: bytes):
        self._ptr = None
        ole32 = ctypes.windll.ole32
        # Ensure COM is initialized on this thread
        ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
        # CoCreateInstance(clsid, NULL, CLSCTX_INPROC_SERVER, iid, &ptr)
        p = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            (ctypes.c_char * 16)(*clsid),
            None,
            1,  # CLSCTX_INPROC_SERVER
            (ctypes.c_char * 16)(*iid),
            ctypes.byref(p),
        )
        if hr < 0 or not p:
            raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08x}")
        self._ptr = p

    def _call(self, idx: int, restype, *argtypes):
        vt = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.c_void_p))[0]
        fn = ctypes.c_void_p(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[idx]).value
        func = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fn)

        def wrapper(*args):
            return func(self._ptr, *args)

        return wrapper

    def release(self):
        if self._ptr:
            self._call(2, wintypes.ULONG)()
            self._ptr = None

    def __del__(self):
        self.release()


# ---------------------------------------------------------------------------
# IIDs
# ---------------------------------------------------------------------------

CLSID_TaskbarList = _pack_guid(
    0x56FDF344, 0xFD6D, 0x11D0, [0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90])

IID_ITaskbarList3 = _pack_guid(
    0xEA1AFB91, 0x9E28, 0x4B86, [0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEF, 0xAF])


# ---------------------------------------------------------------------------
# THUMBBUTTON struct
# ---------------------------------------------------------------------------

class THUMBBUTTON(ctypes.Structure):
    _pack_ = 8
    _fields_ = [
        ("dwMask",  wintypes.DWORD),
        ("iId",     wintypes.DWORD),
        ("iBitmap", wintypes.DWORD),
        ("hIcon",   wintypes.HICON),
        ("szTip",   wintypes.WCHAR * 260),
        ("dwFlags", wintypes.DWORD),
    ]

THB_BITMAP  = 0x0001
THB_ICON    = 0x0002
THB_TOOLTIP = 0x0004
THB_FLAGS   = 0x0008

THBF_ENABLED   = 0x0000
THBF_DISABLED  = 0x0001
THBF_HIDDEN    = 0x0008

# Progress states
TBPF_NOPROGRESS    = 0
TBPF_INDETERMINATE = 1
TBPF_NORMAL        = 2
TBPF_ERROR         = 4
TBPF_PAUSED        = 8


# ---------------------------------------------------------------------------
# TaskbarManager
# ---------------------------------------------------------------------------

class TaskbarManager:
    """Windows taskbar integration — thumbnail buttons + progress bar.

    Usage::

        mgr = TaskbarManager(hwnd)

        # Thumbnail buttons
        mgr.set_buttons([
            (0, "Previous", icon_handle),
            (1, "Play", icon_handle),
            (2, "Next", icon_handle),
        ])
        mgr.on_button_clicked = lambda btn_id: print(f"Button {btn_id}")

        # Progress
        mgr.set_progress(50, 100)   # 50%
        mgr.set_playing(True)       # green bar
        mgr.clear_progress()
    """

    def __init__(self, hwnd: int):
        self._hwnd = hwnd
        self._taskbar = None
        self._buttons = []
        self._button_count = 0
        self._on_button = None
        try:
            self._taskbar = _COM(CLSID_TaskbarList, IID_ITaskbarList3)
            # HrInit at vtable[3]
            self._taskbar._call(3, wintypes.HRESULT)()
        except OSError as e:
            import sys
            print(f"[taskbar] init failed: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Thumbnail toolbar buttons
    # ------------------------------------------------------------------

    def set_buttons(self, buttons: list[tuple[int, str, int]]):
        """Set taskbar thumbnail toolbar buttons.

        *buttons* is a list of ``(id, tooltip, hIcon)`` tuples.
        """
        if not self._taskbar:
            return
        self._buttons = buttons
        self._button_count = len(buttons)

        tb = (THUMBBUTTON * len(buttons))()
        for i, (bid, tip, hicon) in enumerate(buttons):
            tb[i].dwMask = THB_BITMAP | THB_TOOLTIP | THB_FLAGS
            tb[i].iId = bid
            tb[i].iBitmap = 0
            tb[i].hIcon = hicon
            tb[i].szTip = tip
            tb[i].dwFlags = THBF_ENABLED

        # ThumbBarAddButtons at vtable[15]
        self._taskbar._call(
            15, wintypes.HRESULT,
            wintypes.HWND, wintypes.UINT, ctypes.c_void_p,
        )(self._hwnd, len(buttons), tb)

    def set_button_enabled(self, btn_id: int, enabled: bool):
        """Enable or disable a thumbnail button."""
        if not self._taskbar or not self._buttons:
            return
        for bid, tip, hicon in self._buttons:
            if bid == btn_id:
                tb = THUMBBUTTON()
                tb.dwMask = THB_FLAGS
                tb.iId = bid
                tb.dwFlags = THBF_ENABLED if enabled else THBF_DISABLED
                self._taskbar._call(
                    16, wintypes.HRESULT,
                    wintypes.HWND, wintypes.UINT, ctypes.c_void_p,
                )(self._hwnd, 1, ctypes.byref(tb))
                break

    # ------------------------------------------------------------------
    # Progress bar
    # ------------------------------------------------------------------

    def set_progress_state(self, state: int):
        """Set taskbar progress state.

        *state*: TBPF_NOPROGRESS, TBPF_NORMAL, TBPF_PAUSED, TBPF_ERROR, TBPF_INDETERMINATE
        """
        if not self._taskbar:
            return
        # SetProgressState at vtable[10]
        self._taskbar._call(
            10, wintypes.HRESULT,
            wintypes.HWND, wintypes.INT,
        )(self._hwnd, state)

    def set_progress_value(self, completed: int, total: int):
        """Set taskbar progress value."""
        if not self._taskbar:
            return
        # SetProgressValue at vtable[9]
        self._taskbar._call(
            9, wintypes.HRESULT,
            wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong,
        )(self._hwnd, completed, total)

    def set_progress(self, completed: int, total: int):
        """Set progress value. If 0/0, clears progress."""
        if not self._taskbar:
            return
        if total > 0:
            self.set_progress_value(completed, total)
            self.set_progress_state(TBPF_NORMAL)
        else:
            self.set_progress_state(TBPF_NOPROGRESS)

    def set_playing(self, playing: bool):
        """Set progress bar color: green when playing, yellow when paused."""
        if not self._taskbar:
            return
        self.set_progress_state(TBPF_NORMAL if playing else TBPF_PAUSED)

    def clear_progress(self):
        """Remove progress bar from taskbar."""
        if not self._taskbar:
            return
        self.set_progress_state(TBPF_NOPROGRESS)

    def cleanup(self):
        """Release COM resources."""
        self.clear_progress()
        if self._taskbar:
            self._taskbar.release()
            self._taskbar = None
