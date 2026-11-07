"""Keep the display awake on Windows (immersive page)."""

from __future__ import annotations

import ctypes

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


class ScreenInhibitor:
    def __init__(self):
        self._active = False

    def inhibit(self, reason: str = "Immersive playback") -> None:
        if self._active:
            return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
            )
            self._active = True
        except Exception:
            pass

    def uninhibit(self) -> None:
        if not self._active:
            return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        except Exception:
            pass
        self._active = False
