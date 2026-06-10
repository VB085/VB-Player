"""State synchronization polling for DLNA renderers.

Polls GetTransportInfo and GetPositionInfo at regular intervals
and emits signals for UI updates.
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from audio_player.player.dlna.avtransport import (
    AVTransport, parse_duration, parse_position,
)


class StateSyncThread(QThread):
    """Background thread that polls renderer state.

    Signals:
        stateChanged(str)    — transport state (PLAYING, PAUSED_PLAYBACK, STOPPED)
        positionChanged(int) — position in ms
        durationChanged(int) — duration in ms
        error(str)           — polling error
    """

    stateChanged = pyqtSignal(str)
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, avtransport: AVTransport, poll_interval: int = 1000, parent=None):
        super().__init__(parent)
        self._avtransport = avtransport
        self._poll_interval = poll_interval  # ms
        self._running = False
        self._last_state = ""
        self._last_position = -1
        self._last_duration = -1

    def stop(self):
        """Stop polling."""
        self._running = False
        self.wait(3000)

    def run(self):
        """Polling loop — runs in QThread."""
        self._running = True

        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                self.error.emit(str(e))
                # On error, sleep longer before retry
                self.msleep(self._poll_interval * 3)
                continue

            self.msleep(self._poll_interval)

    def _poll_once(self):
        """Single poll cycle: get transport state + position."""
        # Get transport state
        try:
            info = self._avtransport.get_transport_info()
            state = info.get("CurrentTransportState", "")
            if state and state != self._last_state:
                self._last_state = state
                self.stateChanged.emit(state)
        except Exception as e:
            import sys; print(f"[dlna] 状态同步跳过: {e}", file=sys.stderr)

        # Get position
        try:
            pos_info = self._avtransport.get_position_info()
            rel_time = pos_info.get("RelTime", "")
            track_duration = pos_info.get("TrackDuration", "")

            pos_ms = parse_position(rel_time)
            dur_ms = parse_duration(track_duration)

            if pos_ms != self._last_position:
                self._last_position = pos_ms
                self.positionChanged.emit(pos_ms)

            if dur_ms != self._last_duration:
                self._last_duration = dur_ms
                self.durationChanged.emit(dur_ms)

        except Exception as e:
            import sys; print(f"[dlna] 位置同步跳过: {e}", file=sys.stderr)
