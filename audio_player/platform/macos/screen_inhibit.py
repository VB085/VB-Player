"""Keep the display awake on macOS using caffeinate (immersive page)."""

from __future__ import annotations

import subprocess


class ScreenInhibitor:
    def __init__(self):
        self._proc: subprocess.Popen | None = None

    def inhibit(self, reason: str = "Immersive playback") -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        try:
            # -d: prevent display sleep, -i: prevent idle system sleep
            self._proc = subprocess.Popen(
                ["caffeinate", "-d", "-i"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._proc = None

    def uninhibit(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
