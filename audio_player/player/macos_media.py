"""macOS Now Playing service — MPNowPlayingInfoCenter + MPRemoteCommandCenter."""

import sys

from PyQt6.QtCore import QObject, pyqtSignal

from audio_player.player._types import PlaybackState

_HAS_OBJC = False
if sys.platform == "darwin":
    try:
        import MediaPlayer
        import Foundation
        import AppKit
        _HAS_OBJC = True
    except ImportError:
        pass


class MacOSSMediaService(QObject):
    """macOS system media controls via MediaPlayer.framework (pyobjc)."""

    def __init__(self, engine, controller, parent=None):
        super().__init__(parent)
        if not _HAS_OBJC:
            raise ImportError("pyobjc-framework-MediaPlayer is required")

        self._engine = engine
        self._controller = controller

        self._command_center = MediaPlayer.MPRemoteCommandCenter.sharedCommandCenter()
        self._now_playing = MediaPlayer.MPNowPlayingInfoCenter.defaultCenter()

        # Enable commands
        self._command_center.playCommand().addTargetWithAction_(self._on_play)
        self._command_center.pauseCommand().addTargetWithAction_(self._on_pause)
        self._command_center.togglePlayPauseCommand().addTargetWithAction_(self._on_toggle)
        self._command_center.nextTrackCommand().addTargetWithAction_(self._on_next)
        self._command_center.previousTrackCommand().addTargetWithAction_(self._on_prev)
        self._command_center.changePlaybackPositionCommand().addTargetWithAction_(
            self._on_seek
        )

        self._command_center.playCommand().setEnabled_(True)
        self._command_center.pauseCommand().setEnabled_(True)
        self._command_center.togglePlayPauseCommand().setEnabled_(True)
        self._command_center.nextTrackCommand().setEnabled_(True)
        self._command_center.previousTrackCommand().setEnabled_(True)
        self._command_center.changePlaybackPositionCommand().setEnabled_(True)

    def connect_signals(self):
        self._engine.stateChanged.connect(self._on_state_changed)
        self._engine.durationChanged.connect(self._on_duration_changed)
        self._controller.metadataLoaded.connect(self._on_metadata_loaded)

    # ------------------------------------------------------------------
    #  Command handlers
    # ------------------------------------------------------------------

    def _on_play(self, event):
        self._controller.play()
        return MediaPlayer.MPRemoteCommandHandlerStatusSuccess

    def _on_pause(self, event):
        self._controller.pause()
        return MediaPlayer.MPRemoteCommandHandlerStatusSuccess

    def _on_toggle(self, event):
        self._controller.toggle()
        return MediaPlayer.MPRemoteCommandHandlerStatusSuccess

    def _on_next(self, event):
        self._controller.next_track()
        return MediaPlayer.MPRemoteCommandHandlerStatusSuccess

    def _on_prev(self, event):
        self._controller.prev_track()
        return MediaPlayer.MPRemoteCommandHandlerStatusSuccess

    def _on_seek(self, event):
        pos = event.positionTime()
        self._engine.seek(int(pos * 1000))
        return MediaPlayer.MPRemoteCommandHandlerStatusSuccess

    # ------------------------------------------------------------------
    #  State sync
    # ------------------------------------------------------------------

    def _on_state_changed(self, state):
        if state == PlaybackState.Playing:
            playback_state = MediaPlayer.MPNowPlayingPlaybackStatePlaying
        elif state == PlaybackState.Paused:
            playback_state = MediaPlayer.MPNowPlayingPlaybackStatePaused
        else:
            playback_state = MediaPlayer.MPNowPlayingPlaybackStateStopped
        self._now_playing.setPlaybackState_(playback_state)

    def _on_duration_changed(self, ms):
        info = self._now_playing.nowPlayingInfo()
        if info:
            mutable = Foundation.NSMutableDictionary.dictionaryWithDictionary_(info)
            mutable.setObject_forKey_(
                Foundation.NSNumber.numberWithDouble_(ms / 1000.0),
                MediaPlayer.MPMediaItemPropertyPlaybackDuration,
            )
            self._now_playing.setNowPlayingInfo_(mutable)

    def _on_metadata_loaded(self, meta, filepath):
        info = Foundation.NSMutableDictionary.dictionary()

        title = getattr(meta, "title", "") or ""
        artist = getattr(meta, "artist", "") or ""
        album = getattr(meta, "album", "") or ""
        duration = getattr(meta, "duration_seconds", 0) or 0
        track_num = getattr(meta, "track_number", None)

        if title:
            info.setObject_forKey_(title, MediaPlayer.MPMediaItemPropertyTitle)
        if artist:
            info.setObject_forKey_(artist, MediaPlayer.MPMediaItemPropertyArtist)
        if album:
            info.setObject_forKey_(album, MediaPlayer.MPMediaItemPropertyAlbumTitle)
        if duration:
            info.setObject_forKey_(
                Foundation.NSNumber.numberWithDouble_(duration),
                MediaPlayer.MPMediaItemPropertyPlaybackDuration,
            )
        if track_num:
            info.setObject_forKey_(
                Foundation.NSNumber.numberWithInt_(track_num),
                MediaPlayer.MPMediaItemPropertyTrackNumber,
            )

        # Cover art
        cover = getattr(meta, "cover_data", None)
        if cover:
            try:
                ns_data = Foundation.NSData.dataWithBytes_length_(cover, len(cover))
                image = MediaPlayer.MPMediaItemArtwork.initWithBoundsSize_requestHandler_(
                    Foundation.NSSize(300, 300),
                    lambda size: AppKit.NSImage.alloc().initWithData_(ns_data),
                )
                info.setObject_forKey_(image, MediaPlayer.MPMediaItemPropertyArtwork)
            except Exception:
                pass

        self._now_playing.setNowPlayingInfo_(info)

    def cleanup(self):
        self._now_playing.setNowPlayingInfo_(None)
        self._now_playing.setPlaybackState_(
            MediaPlayer.MPNowPlayingPlaybackStateStopped
        )
