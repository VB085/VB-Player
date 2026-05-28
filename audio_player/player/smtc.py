"""Windows System Media Transport Controls (SMTC) service."""

import sys

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_player.player._types import PlaybackState

_HAS_WINSDK = False
if sys.platform == "win32":
    try:
        import winsdk.windows.media as _media
        import winsdk.windows.media.playback as _playback
        import winsdk.windows.storage.streams as _streams
        _HAS_WINSDK = True
    except ImportError:
        pass

_STATUS_MAP = {
    PlaybackState.Playing: _media.MediaPlaybackType.PLAYING if _HAS_WINSDK else None,
    PlaybackState.Paused: _media.MediaPlaybackType.PAUSED if _HAS_WINSDK else None,
    PlaybackState.Stopped: _media.MediaPlaybackType.STOPPED if _HAS_WINSDK else None,
}


class SmtcService(QObject):
    """Windows SMTC service — exposes media controls in the system overlay."""

    def __init__(self, engine, controller, parent=None):
        super().__init__(parent)
        if not _HAS_WINSDK:
            raise ImportError("winsdk is required for SMTC support")

        self._engine = engine
        self._controller = controller

        self._player = _playback.MediaPlayer()
        self._player.auto_play = False
        self._smtc = self._player.system_media_transport_controls
        self._smtc.is_enabled = True

        self._display = self._smtc.display_updater
        self._display.type = _media.MediaPlaybackType.MUSIC

        self._smtc.add_button_pressed(self._on_button_pressed)

        self._smtc.is_play_enabled = True
        self._smtc.is_pause_enabled = True
        self._smtc.is_next_enabled = True
        self._smtc.is_previous_enabled = True

    def connect_signals(self):
        self._engine.stateChanged.connect(self._on_state_changed)
        self._controller.metadataLoaded.connect(self._on_metadata_loaded)

    def _on_state_changed(self, state):
        if state == PlaybackState.Playing:
            self._smtc.playback_status = _media.MediaPlaybackStatus.PLAYING
        elif state == PlaybackState.Paused:
            self._smtc.playback_status = _media.MediaPlaybackStatus.PAUSED
        else:
            self._smtc.playback_status = _media.MediaPlaybackStatus.STOPPED

    def _on_metadata_loaded(self, meta, filepath):
        self._display.clear_all()
        self._display.type = _media.MediaPlaybackType.MUSIC

        music = self._display.music_properties
        music.title = getattr(meta, "title", "") or ""
        music.artist = getattr(meta, "artist", "") or ""
        music.album_title = getattr(meta, "album", "") or ""
        music.album_artist = getattr(meta, "album_artist", "") or ""
        tn = getattr(meta, "track_number", None)
        if tn:
            music.track_number = tn

        cover = getattr(meta, "cover_data", None)
        if cover:
            try:
                stream = _streams.InMemoryRandomAccessStream()
                writer = _streams.DataWriter(stream)
                writer.write_bytes(cover)
                writer.store_async().get()
                writer.detach_stream()
                stream.seek(0)
                self._display.thumbnail = (
                    _streams.RandomAccessStreamReference.create_from_stream(stream)
                )
            except Exception:
                pass

        self._display.update()

    def _on_button_pressed(self, sender, args):
        btn = args.button
        if btn == _media.SystemMediaTransportControlsButton.PLAY:
            QTimer.singleShot(0, self._controller.play)
        elif btn == _media.SystemMediaTransportControlsButton.PAUSE:
            QTimer.singleShot(0, self._controller.pause)
        elif btn == _media.SystemMediaTransportControlsButton.NEXT:
            QTimer.singleShot(0, self._controller.next_track)
        elif btn == _media.SystemMediaTransportControlsButton.PREVIOUS:
            QTimer.singleShot(0, self._controller.prev_track)

    def cleanup(self):
        if self._player:
            self._player.dispose()
            self._player = None
