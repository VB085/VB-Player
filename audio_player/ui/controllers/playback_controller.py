import os
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from audio_player.player.backend import PlaybackBackend, LocalBackend
from audio_player.player.playlist import PlaylistManager, metadata_from_dict
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
    lyricsProvided = pyqtSignal(list)            # external LRC lines (streams)
    externalMetadataReady = pyqtSignal(str, object)  # (filepath, sidecar JSON)
    streamMetadataUpdated = pyqtSignal(dict)     # ICY/HLS tag dict
    contextChanged = pyqtSignal(str)             # "local" | "online"

    def __init__(self, backend: PlaybackBackend, playlist: PlaylistManager,
                 analyzer: AudioAnalyzer, parent=None,
                 online_playlist: PlaylistManager | None = None):
        super().__init__(parent)
        self._backend = backend
        self._local_playlist = playlist
        self._online_playlist = online_playlist or PlaylistManager(self)
        self._playlist = playlist
        self._active_context = "local"
        self._analyzer = analyzer
        self._pending_lyrics: list | None = None
        self._meta_fetching: dict[str, str] = {}
        self._prefetched_lyrics: dict[str, list] = {}
        self.externalMetadataReady.connect(self._on_external_metadata)

    # ------------------------------------------------------------------
    #  Playback context (local library vs online provider)
    # ------------------------------------------------------------------

    @property
    def active_context(self) -> str:
        return self._active_context

    @property
    def active_playlist(self) -> PlaylistManager:
        return self._playlist

    @property
    def local_playlist(self) -> PlaylistManager:
        return self._local_playlist

    @property
    def online_playlist(self) -> PlaylistManager:
        return self._online_playlist

    def set_active_context(self, context: str):
        if context not in ("local", "online"):
            return
        if context == self._active_context:
            return
        self._active_context = context
        self._playlist = (
            self._online_playlist if context == "online" else self._local_playlist
        )
        self._pending_lyrics = None
        self._prefetched_lyrics.clear()
        self.contextChanged.emit(context)

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
        if self._pending_lyrics is not None:
            lines = self._pending_lyrics
            self._pending_lyrics = None
            self.lyricsProvided.emit(lines)
        elif filepath in self._prefetched_lyrics:
            self.lyricsProvided.emit(self._prefetched_lyrics.pop(filepath))
        else:
            self._analyzer.analyze(filepath)
        meta_url = getattr(meta, "meta_url", "")
        if meta_url and (not meta.cover_data or not meta.sample_rate):
            self._fetch_external_metadata(filepath, meta_url)
        self._prefetch_neighbors()
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
        self._pending_lyrics = None
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

    def open_external_stream(self, url: str, metadata: dict | None = None):
        """Play a stream supplied by an external source (e.g. MPRIS OpenUri).

        *metadata* may carry title/artist/album/duration/cover_data/lyrics.
        Lyrics are LRC text and are fed straight to the lyrics overlay because
        AudioAnalyzer intentionally ignores URL sources.
        """
        self.set_active_context("online")
        meta = dict(metadata or {})
        lyrics_text = str(meta.pop("lyrics", "") or "")
        self._pending_lyrics = None
        if lyrics_text:
            from audio_player.player.lrc_parser import parse_lrc
            self._pending_lyrics = parse_lrc(lyrics_text)
        self._online_playlist.add_url(url, metadata=meta or None)
        self._online_playlist.current_index = self._online_playlist.count - 1

    def open_external_playlist(self, items: list[tuple[str, dict]], start_index: int = 0):
        """Replace the playlist with an external list and start at *start_index*.

        Items are (uri, metadata); non-start items may carry a ``meta_url``
        sidecar that is fetched lazily when the track starts.
        """
        self.set_active_context("online")
        self._pending_lyrics = None
        self._prefetched_lyrics.clear()
        self._online_playlist.set_urls([(uri, meta or {}) for uri, meta in items])
        if not items:
            return
        index = max(0, min(int(start_index), len(items) - 1))
        selected = items[index][1] or {}
        lyrics_text = str(selected.get("lyrics") or "")
        if lyrics_text:
            from audio_player.player.lrc_parser import parse_lrc
            self._pending_lyrics = parse_lrc(lyrics_text)
        self._online_playlist.current_index = index

    # ------------------------------------------------------------------
    #  Lazy metadata sidecar (external streams)
    # ------------------------------------------------------------------

    def _fetch_external_metadata(self, filepath: str, url: str):
        if filepath in self._meta_fetching:
            return
        self._meta_fetching[filepath] = url

        def worker():
            import json
            import urllib.request
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except Exception:
                self._meta_fetching.pop(filepath, None)
                return
            self.externalMetadataReady.emit(filepath, data)

        threading.Thread(target=worker, daemon=True).start()

    def _prefetch_neighbors(self, count: int = 3):
        """Warm metadata (original cover/lyrics/specs) for upcoming tracks."""
        playlist = self._playlist
        index = playlist.current_index
        if index < 0:
            return
        for offset in range(1, count + 1):
            row = index + offset
            if row >= playlist.count:
                break
            track = playlist.track_at(row)
            meta = playlist.track_metadata(row)
            if not track or meta is None:
                continue
            meta_url = getattr(meta, "meta_url", "")
            if not meta_url:
                continue
            if meta.cover_data and meta.sample_rate:
                continue
            self._fetch_external_metadata(track["path"], meta_url)

        if playlist is self._online_playlist:
            keep = set(range(max(0, index - 4), min(playlist.count, index + 5)))
            playlist.trim_stream_covers(keep)

    def _on_external_metadata(self, filepath: str, data: dict):
        self._meta_fetching.pop(filepath, None)
        if not isinstance(data, dict):
            return
        data = dict(data)
        lyrics_text = str(data.pop("lyrics", "") or "")
        cover_b64 = str(data.pop("cover_b64", "") or "")
        if cover_b64:
            import base64
            try:
                data["cover_data"] = base64.b64decode(cover_b64)
            except Exception:
                pass
        meta = metadata_from_dict(data)
        if meta is None:
            return
        index = self._playlist.index_of_path(filepath)
        if index < 0:
            return
        old = self._playlist.track_metadata(index)
        if old is not None:
            # Preserve sidecar/thumbnail hints lost from the /meta payload.
            meta.meta_url = getattr(old, "meta_url", "")
            meta.cover_url = getattr(old, "cover_url", "")
            if not meta.cover_data and old.cover_data:
                meta.cover_data = old.cover_data
        self._playlist.update_metadata(index, meta)
        lines = None
        if lyrics_text:
            from audio_player.player.lrc_parser import parse_lrc
            lines = parse_lrc(lyrics_text)
        is_current = getattr(self._backend, "current_source", "") == filepath
        if is_current:
            self.metadataLoaded.emit(meta, filepath)
            self.trackLoaded.emit(filepath)
            if lines:
                self.lyricsProvided.emit(lines)
        elif lines:
            self._prefetched_lyrics[filepath] = lines
            if len(self._prefetched_lyrics) > 20:
                self._prefetched_lyrics.pop(next(iter(self._prefetched_lyrics)))
