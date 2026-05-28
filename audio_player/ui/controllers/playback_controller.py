import os

from PyQt6.QtCore import QObject, pyqtSignal

from audio_player.player.engine import AudioEngine
from audio_player.player.playlist import PlaylistManager
from audio_player.player.audio_analyzer import AudioAnalyzer
from audio_player.player.metadata import read_metadata, TrackMetadata
from audio_player.i18n import _


_AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".ogg", ".opus",
    ".m4a", ".aac", ".wma", ".aiff", ".ape", ".wv",
    ".dsf", ".dff",
}


class PlaybackController(QObject):
    """Controller for engine callbacks and playlist actions (Groups 3+4)."""

    trackLoaded = pyqtSignal(str)               # filepath when a new track is loaded
    playbackStateChanged = pyqtSignal(bool)      # is_playing
    logMessage = pyqtSignal(str)                 # status bar text
    errorOccurred = pyqtSignal(str)              # error message
    metadataLoaded = pyqtSignal(object, str)     # (TrackMetadata, filepath)
    streamMetadataUpdated = pyqtSignal(dict)     # ICY/HLS tag dict

    def __init__(self, engine: AudioEngine, playlist: PlaylistManager,
                 analyzer: AudioAnalyzer, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._playlist = playlist
        self._analyzer = analyzer

    # ------------------------------------------------------------------
    #  Engine signal wiring
    # ------------------------------------------------------------------

    def connect_engine(self):
        """Connect all engine signals to internal handlers."""
        self._engine.stateChanged.connect(self._on_state_changed)
        self._engine.positionChanged.connect(self._on_position_changed)
        self._engine.durationChanged.connect(self._on_duration_changed)
        self._engine.trackChanged.connect(self._on_track_changed)
        self._engine.trackFinished.connect(self._on_track_finished)
        self._engine.errorOccurred.connect(self._on_error)
        self._engine.volumeChanged.connect(lambda v: None)  # handled elsewhere
        self._engine.streamMetadataChanged.connect(self._on_stream_metadata)

    # ------------------------------------------------------------------
    #  Engine callbacks
    # ------------------------------------------------------------------

    def _on_state_changed(self, state):
        from audio_player.player._types import PlaybackState
        self.playbackStateChanged.emit(state == PlaybackState.Playing)

    def _on_position_changed(self, ms):
        dur = self._engine.duration
        if dur > 0:
            ratio = ms / dur
            # Ratio is exposed via signal for external consumers (waveform, spectrum)
            # Individual widgets are connected directly in MainWindow
            pass

    def _on_duration_changed(self, ms):
        pass  # Duration updates are handled by direct widget connections in MainWindow

    def _on_track_changed(self, filepath):
        is_url = filepath.startswith(("http://", "https://", "smb://"))
        if is_url:
            from urllib.parse import urlparse
            meta = read_metadata(filepath)
            title = meta.title or urlparse(filepath).hostname or filepath
            artist = meta.artist or ""
        else:
            meta = read_metadata(filepath)
            title = meta.title or os.path.basename(filepath)
            artist = meta.artist or ""
        if artist:
            self.logMessage.emit(_("log.now_playing", artist=artist, title=title))
        else:
            self.logMessage.emit(_("log.now_playing_no_artist", title=title))
        self.metadataLoaded.emit(meta, filepath)
        self.trackLoaded.emit(filepath)
        self._analyzer.analyze(filepath)
        self._update_gapless_next_path()

    def _on_track_finished(self):
        # If gapless transition happened, the engine already swapped pipelines.
        # Just advance the playlist index to stay in sync (don't load/play again).
        if self._engine._gapless_enabled and self._engine._preload_pipeline is None and self._engine.is_playing:
            self._playlist.advance()
            self._update_gapless_next_path()
            return
        if self._playlist.advance():
            path = self._playlist.current_track_path
            if path:
                self._engine.load(path)
                self._engine.play()
        else:
            self._engine.stop()

    def _update_gapless_next_path(self):
        """Update the engine's next-path hint for gapless preload."""
        self._engine._gapless_next_path = self._playlist.peek_next_path()

    def _on_error(self, msg):
        self.logMessage.emit(_("log.error", msg=msg))
        self.errorOccurred.emit(msg)

    def _on_stream_metadata(self, tags: dict):
        """Handle ICY/HLS metadata from stream."""
        self.streamMetadataUpdated.emit(tags)

    def on_playlist_index_changed(self, idx):
        # Skip if gapless transition already handled the track change
        if self._engine._gapless_enabled and self._engine.is_playing:
            self._update_gapless_next_path()
            return
        path = self._playlist.current_track_path
        if path:
            self._engine.load(path)
            self._engine.play()

    # ------------------------------------------------------------------
    #  Playlist actions
    # ------------------------------------------------------------------

    def play_track_at(self, idx):
        """Play track at *idx*.  If already current, seek to 0 and play."""
        if idx == self._playlist.current_index and self._playlist.current_track_path:
            self._engine.seek(0)
            self._engine.play()
        else:
            self._playlist.current_index = idx

    def next_track(self):
        """Advance to next track in playlist."""
        if self._playlist.advance():
            path = self._playlist.current_track_path
            if path:
                self._engine.load(path)
                self._engine.play()

    def prev_track(self):
        """Seek to 0 if >3 s into track, otherwise go to previous track."""
        if self._engine.position > 3000:
            self._engine.seek(0)
        elif self._playlist.previous():
            path = self._playlist.current_track_path
            if path:
                self._engine.load(path)
                self._engine.play()

    # ------------------------------------------------------------------
    #  Transport delegation
    # ------------------------------------------------------------------

    def play(self):
        self._engine.play()

    def pause(self):
        self._engine.pause()

    def toggle(self):
        self._engine.toggle()

    def stop(self):
        self._engine.stop()

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

    def load_and_play(self, paths: list[str]):
        """Clear playlist, load *paths*, and play the first track."""
        self._playlist.clear()
        self.load_paths(paths)
        if self._playlist.count > 0:
            self._playlist.current_index = 0
