import os

from PyQt6.QtCore import QObject, pyqtSignal

from audio_player.player.backend import PlaybackBackend, LocalBackend
from audio_player.player.playlist import PlaylistManager
from audio_player.player.audio_analyzer import AudioAnalyzer
from audio_player.player.metadata import read_metadata, TrackMetadata
from audio_player.i18n import _


from audio_player.player._types import AUDIO_EXTENSIONS as _AUDIO_EXTENSIONS


class PlaybackController(QObject):
    """Controller for backend callbacks and playlist actions."""

    trackLoaded = pyqtSignal(str)               # filepath when a new track is loaded
    playbackStateChanged = pyqtSignal(bool)      # is_playing
    logMessage = pyqtSignal(str)                 # status bar text
    errorOccurred = pyqtSignal(str)              # error message
    metadataLoaded = pyqtSignal(object, str)     # (TrackMetadata, filepath)
    streamMetadataUpdated = pyqtSignal(dict)     # ICY/HLS tag dict

    def __init__(self, backend: PlaybackBackend, playlist: PlaylistManager,
                 analyzer: AudioAnalyzer, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._playlist = playlist
        self._analyzer = analyzer

    # ------------------------------------------------------------------
    #  Backend signal wiring
    # ------------------------------------------------------------------

    def connect_engine(self):
        """Connect backend signals to internal handlers."""
        self._backend.stateChanged.connect(self._on_state_changed)
        self._backend.positionChanged.connect(self._on_position_changed)
        self._backend.durationChanged.connect(self._on_duration_changed)
        self._backend.trackChanged.connect(self._on_track_changed)
        self._backend.trackFinished.connect(self._on_track_finished)
        self._backend.errorOccurred.connect(self._on_error)
        self._backend.volumeChanged.connect(lambda v: None)  # handled elsewhere
        # Engine-specific signals (LocalBackend only)
        if isinstance(self._backend, LocalBackend):
            engine = self._backend.engine
            if hasattr(engine, 'streamMetadataChanged'):
                engine.streamMetadataChanged.connect(self._on_stream_metadata)

    def switch_backend(self, new_backend):
        """Reconnect signals to a new backend after device switch."""
        # Disconnect old backend
        try:
            self._backend.stateChanged.disconnect(self._on_state_changed)
            self._backend.positionChanged.disconnect(self._on_position_changed)
            self._backend.durationChanged.disconnect(self._on_duration_changed)
            self._backend.trackChanged.disconnect(self._on_track_changed)
            self._backend.trackFinished.disconnect(self._on_track_finished)
            self._backend.errorOccurred.disconnect(self._on_error)
        except TypeError:
            pass  # not connected

        self._backend = new_backend
        self.connect_engine()

    # ------------------------------------------------------------------
    #  Engine callbacks
    # ------------------------------------------------------------------

    def _on_state_changed(self, state):
        from audio_player.player._types import PlaybackState
        self.playbackStateChanged.emit(state == PlaybackState.Playing)

    def _on_position_changed(self, ms):
        dur = self._backend.duration
        if dur > 0:
            ratio = ms / dur
            # Ratio is exposed via signal for external consumers (waveform, spectrum)
            # Individual widgets are connected directly in MainWindow
            pass

    def _on_duration_changed(self, ms):
        pass  # Duration updates are handled by direct widget connections in MainWindow

    def _on_track_changed(self, filepath):
        is_url = filepath.startswith(("http://", "https://", "smb://"))
        # Use cached metadata from playlist to avoid thread-unsafe read_metadata
        meta = self._playlist.track_metadata(self._playlist.current_index)
        if meta is None:
            meta = read_metadata(filepath)
        if is_url:
            from urllib.parse import urlparse
            title = meta.title or urlparse(filepath).hostname or filepath
            artist = meta.artist or ""
        else:
            title = meta.title or os.path.basename(filepath)
            artist = meta.artist or ""
        if artist:
            self.logMessage.emit(_("log.now_playing", artist=artist, title=title))
        else:
            self.logMessage.emit(_("log.now_playing_no_artist", title=title))
        self.metadataLoaded.emit(meta, filepath)
        self.trackLoaded.emit(filepath)
        if self._analyzer is not None:
            self._analyzer.analyze(filepath)
        self._update_gapless_next_path()

    def _on_track_finished(self):
        # If gapless transition happened, the engine already swapped pipelines.
        # Just advance the playlist index to stay in sync (don't load/play again).
        if isinstance(self._backend, LocalBackend):
            engine = self._backend.engine
            if engine._gapless_enabled and engine._preload_pipeline is None and engine.is_playing:
                self._playlist.advance()
                self._update_gapless_next_path()
                return
        if self._playlist.advance():
            path = self._playlist.current_track_path
            if path:
                self._backend.load(path)
                self._backend.play()
        else:
            self._backend.stop()

    def _update_gapless_next_path(self):
        """Update the engine's next-path hint for gapless preload."""
        if isinstance(self._backend, LocalBackend):
            self._backend.engine._gapless_next_path = self._playlist.peek_next_path()

    def _on_error(self, msg):
        self.logMessage.emit(_("log.error", msg=msg))
        self.errorOccurred.emit(msg)

    def _on_stream_metadata(self, tags: dict):
        """Handle ICY/HLS metadata from stream."""
        self.streamMetadataUpdated.emit(tags)

    def on_playlist_index_changed(self, idx):
        # Skip if gapless transition already handled the track change
        if isinstance(self._backend, LocalBackend):
            engine = self._backend.engine
            if engine._gapless_enabled and engine.is_playing:
                self._update_gapless_next_path()
                return
        path = self._playlist.current_track_path
        if path:
            self._backend.load(path)
            self._backend.play()

    # ------------------------------------------------------------------
    #  Playlist actions
    # ------------------------------------------------------------------

    def play_track_at(self, idx):
        """Play track at *idx*."""
        if not (0 <= idx < self._playlist.count):
            return
        if idx == self._playlist.current_index and self._playlist.current_track_path:
            self._backend.seek(0)
            self._backend.play()
        else:
            self._playlist.current_index = idx  # triggers on_playlist_index_changed → load+play

    def next_track(self):
        """Advance to next track in playlist."""
        if self._playlist.advance():
            path = self._playlist.current_track_path
            if path:
                self._backend.load(path)
                self._backend.play()

    def prev_track(self):
        """Seek to 0 if >3 s into track, otherwise go to previous track."""
        if self._backend.position > 3000:
            self._backend.seek(0)
        elif self._playlist.previous():
            path = self._playlist.current_track_path
            if path:
                self._backend.load(path)
                self._backend.play()

    # ------------------------------------------------------------------
    #  Transport delegation
    # ------------------------------------------------------------------

    def play(self):
        self._backend.play()

    def pause(self):
        self._backend.pause()

    def toggle(self):
        self._backend.toggle()

    def stop(self):
        self._backend.stop()

    # ------------------------------------------------------------------
    #  Path loading
    # ------------------------------------------------------------------

    def load_paths(self, paths: list[str]):
        """Filter audio files from *paths* (dirs expanded) and add to playlist."""
        audio_paths = []
        for p in paths:
            if os.path.isdir(p):
                audio_paths.extend(
                    os.path.join(p, f) for f in os.listdir(p)
                    if os.path.splitext(f)[1].lower() in _AUDIO_EXTENSIONS
                )
            else:
                audio_paths.append(p)
        if audio_paths:
            self._playlist.add_files(sorted(audio_paths))
            if self._playlist.current_index < 0:
                self._playlist.current_index = 0

    def load_and_play(self, paths: list[str], start_idx: int = 0):
        """Load *paths* into playlist and play *start_idx* (default first)."""
        self.load_paths(paths)
        if self._playlist.count > start_idx:
            self._playlist.current_index = start_idx
