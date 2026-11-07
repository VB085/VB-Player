"""External stream metadata + lyrics hand-off (MPRIS OpenUriWithMetadata)."""

from PyQt6.QtCore import QObject

from audio_player.player.playlist import PlaylistManager
from audio_player.player.lrc_parser import parse_lrc
from audio_player.ui.controllers.playback_controller import PlaybackController


class _DummyBackend(QObject):
    duration = 0


class _DummyAnalyzer:
    def __init__(self):
        self.paths = []

    def analyze(self, path):
        self.paths.append(path)


def test_external_lyrics_are_emitted_instead_of_analyzer(qapp):
    playlist = PlaylistManager()
    analyzer = _DummyAnalyzer()
    ctrl = PlaybackController(_DummyBackend(), playlist, analyzer)
    try:
        playlist.add_url(
            "http://127.0.0.1:8765/stream/abc",
            metadata={
                "title": "晴天",
                "artist": "周杰伦",
                "album": "叶惠美",
                "duration_ms": 269000,
                "format": "FLAC",
                "lyrics": "[00:01.00]第一句",
            },
        )
        playlist.current_index = 0
        ctrl._pending_lyrics = parse_lrc("[00:01.00]第一句")

        received = []
        ctrl.lyricsProvided.connect(received.extend)
        ctrl._on_track_changed("http://127.0.0.1:8765/stream/abc")

        assert received and received[0].text == "第一句"
        assert analyzer.paths == []  # analyzer must not touch URL streams
        assert ctrl._pending_lyrics is None
    finally:
        playlist.shutdown()


def test_sidecar_metadata_updates_playlist_and_cover(qapp):
    import base64

    playlist = PlaylistManager()
    ctrl = PlaybackController(_DummyBackend(), playlist, _DummyAnalyzer())
    try:
        playlist.set_urls([
            ("http://127.0.0.1:8765/stream/1", {
                "title": "第一首", "artist": "A",
                "meta_url": "http://127.0.0.1:8765/meta/1",
            }),
        ])
        ctrl._on_external_metadata("http://127.0.0.1:8765/stream/1", {
            "title": "第一首",
            "artist": "A",
            "album": "专辑",
            "format": "FLAC",
            "sample_rate": 44100,
            "bits_per_sample": 24,
            "bitrate": 1643,
            "channels": 2,
            "lyrics": "[00:01.00]第一句",
            "cover_b64": base64.b64encode(b"fake-jpeg").decode("ascii"),
        })
        meta = playlist.track_metadata(0)
        assert meta.album == "专辑"
        assert meta.format == "FLAC"
        assert meta.sample_rate == 44100
        assert meta.cover_data == b"fake-jpeg"
    finally:
        playlist.shutdown()


def test_prefetches_next_tracks_and_lyrics(qapp):
    playlist = PlaylistManager()
    analyzer = _DummyAnalyzer()
    ctrl = PlaybackController(_DummyBackend(), playlist, analyzer,
                              online_playlist=playlist)
    try:
        playlist.set_urls([
            ("http://127.0.0.1:8765/stream/1", {"title": "1", "meta_url": "http://m/1"}),
            ("http://127.0.0.1:8765/stream/2", {"title": "2", "meta_url": "http://m/2"}),
            ("http://127.0.0.1:8765/stream/3", {"title": "3", "meta_url": "http://m/3"}),
        ])
        ctrl.set_active_context("online")
        fetched = []
        ctrl._fetch_external_metadata = lambda path, url: fetched.append(path)
        playlist.current_index = 0

        ctrl._on_track_changed("http://127.0.0.1:8765/stream/1")

        assert fetched == [
            "http://127.0.0.1:8765/stream/1",
            "http://127.0.0.1:8765/stream/2",
            "http://127.0.0.1:8765/stream/3",
        ]

        ctrl._on_external_metadata("http://127.0.0.1:8765/stream/2", {
            "title": "2", "sample_rate": 44100, "bits_per_sample": 24,
            "lyrics": "[00:01.00]第二首",
        })
        assert "http://127.0.0.1:8765/stream/2" in ctrl._prefetched_lyrics
        received = []
        analyzer.paths.clear()
        ctrl.lyricsProvided.connect(received.extend)
        ctrl._on_track_changed("http://127.0.0.1:8765/stream/2")
        assert received and received[0].text == "第二首"
        assert "http://127.0.0.1:8765/stream/2" not in analyzer.paths
    finally:
        playlist.shutdown()
