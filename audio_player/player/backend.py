"""PlaybackBackend abstraction — single active backend at a time.

LocalBackend wraps GStreamer AudioEngine.
DLNABackend (future) wraps UPnP renderer control.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from audio_player.i18n import _

from PyQt6.QtCore import QObject, pyqtSignal

from audio_player.player._types import PlaybackState


class PlaybackBackend(QObject):
    """Abstract playback backend with shared signal interface.

    Subclasses must implement all abstract methods.
    Only one backend is active at a time — CastController manages switching.
    """

    # Signals shared by all backends
    stateChanged = pyqtSignal(int)       # PlaybackState
    positionChanged = pyqtSignal(int)    # ms
    durationChanged = pyqtSignal(int)    # ms
    trackChanged = pyqtSignal(str)       # path or URI
    trackFinished = pyqtSignal()
    errorOccurred = pyqtSignal(str)
    volumeChanged = pyqtSignal(float)    # 0.0–1.0

    def __init__(self, parent=None):
        super().__init__(parent)

    # ------------------------------------------------------------------
    #  Abstract playback control
    # ------------------------------------------------------------------

    @abstractmethod
    def load(self, source: str) -> None:
        """Load a file path or URL."""

    @abstractmethod
    def play(self) -> None:
        """Start or resume playback."""

    @abstractmethod
    def pause(self) -> None:
        """Pause playback."""

    @abstractmethod
    def stop(self) -> None:
        """Stop playback and release resources."""

    @abstractmethod
    def toggle(self) -> None:
        """Toggle play/pause."""

    @abstractmethod
    def seek(self, position_ms: int) -> None:
        """Seek to position in milliseconds."""

    # ------------------------------------------------------------------
    #  Abstract properties
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def position(self) -> int:
        """Current position in ms."""

    @property
    @abstractmethod
    def duration(self) -> int:
        """Duration in ms."""

    @property
    @abstractmethod
    def state(self) -> int:
        """Current PlaybackState."""

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """True if currently playing."""

    @property
    @abstractmethod
    def current_source(self) -> str:
        """Current file path or URL."""

    @property
    @abstractmethod
    def volume(self) -> float:
        """Volume level 0.0–1.0."""

    @volume.setter
    @abstractmethod
    def volume(self, value: float) -> None:
        """Set volume level."""

    # ------------------------------------------------------------------
    #  Backend lifecycle
    # ------------------------------------------------------------------

    def activate(self) -> None:
        """Called when this backend becomes active. Override if needed."""

    def deactivate(self) -> None:
        """Called when switching away from this backend. Override if needed."""


class LocalBackend(PlaybackBackend):
    """Wraps existing GStreamer AudioEngine as a PlaybackBackend."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine

        # Forward engine signals
        self._engine.stateChanged.connect(self.stateChanged.emit)
        self._engine.positionChanged.connect(self.positionChanged.emit)
        self._engine.durationChanged.connect(self.durationChanged.emit)
        self._engine.trackChanged.connect(self.trackChanged.emit)
        self._engine.trackFinished.connect(self.trackFinished.emit)
        self._engine.errorOccurred.connect(self.errorOccurred.emit)
        self._engine.volumeChanged.connect(self.volumeChanged.emit)

    @property
    def engine(self):
        """Direct engine access for engine-specific operations (gapless, DSD, etc.)."""
        return self._engine

    # ------------------------------------------------------------------
    #  Playback control
    # ------------------------------------------------------------------

    def load(self, source: str) -> None:
        self._engine.load(source)

    def play(self) -> None:
        self._engine.play()

    def pause(self) -> None:
        self._engine.pause()

    def stop(self) -> None:
        self._engine.stop()

    def toggle(self) -> None:
        self._engine.toggle()

    def seek(self, position_ms: int) -> None:
        self._engine.seek(position_ms)

    # ------------------------------------------------------------------
    #  Properties
    # ------------------------------------------------------------------

    @property
    def position(self) -> int:
        return self._engine.position

    @property
    def duration(self) -> int:
        return self._engine.duration

    @property
    def state(self) -> int:
        return self._engine.state

    @property
    def is_playing(self) -> bool:
        return self._engine.is_playing

    @property
    def current_source(self) -> str:
        return self._engine.current_file

    @property
    def volume(self) -> float:
        return self._engine.volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._engine.volume = value

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    def deactivate(self) -> None:
        """Stop engine and release pipeline."""
        self._engine.stop()


class DLNABackend(PlaybackBackend):
    """Wraps UPnP AVTransport as a PlaybackBackend.

    Renderer pulls audio from EmbeddedHttpServer; this backend sends
    play/pause/stop/seek commands via SOAP.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avtransport = None
        self._current_source = ""
        self._position_ms = 0
        self._duration_ms = 0
        self._state = PlaybackState.Stopped

    def set_avtransport(self, avtransport) -> None:
        """Set the AVTransport client (from device info)."""
        self._avtransport = avtransport

    # ------------------------------------------------------------------
    #  Playback control
    # ------------------------------------------------------------------

    def load(self, source: str) -> None:
        """Set the URI on the renderer (source is HTTP URL)."""
        if self._avtransport is None:
            self.errorOccurred.emit(_("device.not_connected"))
            return
        try:
            self._avtransport.set_av_transport_uri(source)
            self._current_source = source
            self.trackChanged.emit(source)
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def play(self) -> None:
        if self._avtransport is None:
            return
        try:
            self._avtransport.play()
            self._state = PlaybackState.Playing
            self.stateChanged.emit(PlaybackState.Playing)
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def pause(self) -> None:
        if self._avtransport is None:
            return
        try:
            self._avtransport.pause()
            self._state = PlaybackState.Paused
            self.stateChanged.emit(PlaybackState.Paused)
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def stop(self) -> None:
        if self._avtransport is None:
            return
        try:
            self._avtransport.stop()
            self._state = PlaybackState.Stopped
            self._position_ms = 0
            self.stateChanged.emit(PlaybackState.Stopped)
            self.positionChanged.emit(0)
        except Exception as e:
            self.errorOccurred.emit(str(e))

    def toggle(self) -> None:
        if self._state == PlaybackState.Playing:
            self.pause()
        else:
            self.play()

    def seek(self, position_ms: int) -> None:
        if self._avtransport is None:
            return
        try:
            seconds = position_ms // 1000
            self._avtransport.seek_seconds(seconds)
        except Exception as e:
            self.errorOccurred.emit(str(e))

    # ------------------------------------------------------------------
    #  Properties
    # ------------------------------------------------------------------

    @property
    def position(self) -> int:
        return self._position_ms

    @property
    def duration(self) -> int:
        return self._duration_ms

    @property
    def state(self) -> int:
        return self._state

    @property
    def is_playing(self) -> bool:
        return self._state == PlaybackState.Playing

    @property
    def current_source(self) -> str:
        return self._current_source

    @property
    def volume(self) -> float:
        return 1.0  # volume controlled by renderer hardware

    @volume.setter
    def volume(self, value: float) -> None:
        pass  # no-op, renderer controls volume

    # ------------------------------------------------------------------
    #  State sync (called by polling thread)
    # ------------------------------------------------------------------

    def update_state(self, transport_state: str) -> None:
        """Update playback state from renderer transport state."""
        from audio_player.player.dlna.avtransport import parse_duration
        state_map = {
            "PLAYING": PlaybackState.Playing,
            "PAUSED_PLAYBACK": PlaybackState.Paused,
            "STOPPED": PlaybackState.Stopped,
            "NO_MEDIA_PRESENT": PlaybackState.Stopped,
        }
        new_state = state_map.get(transport_state)
        if new_state is not None and new_state != self._state:
            self._state = new_state
            self.stateChanged.emit(new_state)

    def update_position(self, position_ms: int, duration_ms: int) -> None:
        """Update position/duration from renderer."""
        if position_ms != self._position_ms:
            self._position_ms = position_ms
            self.positionChanged.emit(position_ms)
        if duration_ms != self._duration_ms:
            self._duration_ms = duration_ms
            self.durationChanged.emit(duration_ms)

    def update_position_pos(self, position_ms: int) -> None:
        """Update position from polling thread."""
        if position_ms != self._position_ms:
            self._position_ms = position_ms
            self.positionChanged.emit(position_ms)

    def update_position_dur(self, duration_ms: int) -> None:
        """Update duration from polling thread."""
        if duration_ms != self._duration_ms:
            self._duration_ms = duration_ms
            self.durationChanged.emit(duration_ms)

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    def activate(self) -> None:
        """Prepare for DLNA playback."""
        self._position_ms = 0
        self._duration_ms = 0
        self._state = PlaybackState.Stopped

    def deactivate(self) -> None:
        """Stop renderer and clean up."""
        if self._avtransport is not None:
            try:
                self._avtransport.stop()
            except Exception as _e:
                import sys; print(f"[{__name__}] {_e}", file=sys.stderr)
        self._state = PlaybackState.Stopped
        self._position_ms = 0
        self._current_source = ""
