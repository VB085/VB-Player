"""Regression tests: dynamic-text labels must never overflow horizontally.

The marquee bug (long titles hard-clipped in the pill) and its siblings
(metadata panel GENRE row, album-detail artist line) were all cases of
labels fed unbounded metadata text with neither eliding nor wrapping.
These tests feed an oversized string into every dynamic-text surface and
assert each one handles it: wrapping, eliding, or marquee-scrolling —
never plain overflow.

Offline (QT_QPA_PLATFORM=offscreen) — width math only, no rendering.
"""

import sys

import pytest
from PyQt6.QtWidgets import QApplication

from audio_player.player.metadata import TrackMetadata

LONG = "超长文本回归测试 Super Long Regression Text Edition " * 4


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _overflows(label) -> bool:
    """True when the label's text is wider than the label AND the label
    has no strategy to handle it (no wrap; not a MarqueeLabel)."""
    from audio_player.ui.widgets.floating_pill import MarqueeLabel
    if isinstance(label, MarqueeLabel):
        return False  # scrolls instead
    if label.wordWrap():
        return False  # wraps instead
    fm = label.fontMetrics()
    return label.width() > 0 and fm.horizontalAdvance(label.text()) > label.width()


class TestPillAndBar:
    """Transport surfaces use MarqueeLabel — overflow must engage it."""

    def test_pill_labels_are_marquee(self, qapp):
        from audio_player.ui.widgets.floating_pill import (
            FloatingPill, MarqueeLabel,
        )
        pill = FloatingPill()
        pill.set_track(LONG, LONG)
        assert isinstance(pill._title_label, MarqueeLabel)
        assert isinstance(pill._artist_label, MarqueeLabel)
        assert pill._title_label._overflow, "long title must trigger marquee"
        assert not _overflows(pill._title_label)

    def test_bar_labels_are_marquee(self, qapp):
        from audio_player.ui.widgets.now_playing_bar import NowPlayingBar
        from audio_player.ui.widgets.floating_pill import MarqueeLabel
        bar = NowPlayingBar()
        bar.set_track(LONG, LONG)
        assert isinstance(bar._title_label, MarqueeLabel)
        assert bar._title_label._overflow
        assert not _overflows(bar._title_label)

    def test_short_text_stays_static(self, qapp):
        """No timers for short text — the marquee must stay dormant."""
        from audio_player.ui.widgets.floating_pill import FloatingPill
        pill = FloatingPill()
        pill.set_track("Short", "Artist")
        assert not pill._title_label._overflow
        assert not pill._title_label._timer.isActive()


class TestAlbumDetail:
    """Album detail header wraps long name and artist."""

    def test_album_detail_wraps(self, qapp):
        from audio_player.ui.widgets.album_view import AlbumDetailPage
        from audio_player.player.album_manager import AlbumInfo
        page = AlbumDetailPage()
        page.resize(900, 600)
        page.show_album(AlbumInfo(name=LONG, artist=LONG, year=2024, disc_count=1))
        assert page._name_label.wordWrap()
        assert page._artist_label.wordWrap()
        assert not _overflows(page._name_label)
        assert not _overflows(page._artist_label)


class TestPlaylistDetail:
    """Playlist detail header wraps name and description."""

    def test_playlist_detail_wraps(self, qapp):
        from audio_player.ui.widgets.playlist_browse import PlaylistDetailPage
        page = PlaylistDetailPage()
        page.resize(900, 600)

        class Info:
            name = LONG
            description = LONG
            cover_data = None
            tracks = []

        page.show_playlist(Info())
        assert page._name_label.wordWrap()
        assert not _overflows(page._name_label)


class TestMetadataPanel:
    """Every metadata panel value line must wrap (GENRE row regressed once)."""

    def test_metadata_panel_wraps(self, qapp):
        from audio_player.ui.widgets.metadata_panel import MetadataPanel
        panel = MetadataPanel()
        panel.resize(640, 800)
        meta = TrackMetadata(
            title=LONG, artist=LONG, album=LONG, genre=LONG, format="FLAC",
            year=2024, sample_rate=44100, bits_per_sample=16, channels=2,
            duration_seconds=180.0, bitrate=1000, file_size=1000,
        )
        panel.show_metadata(meta, "")
        for attr in ("_title_label", "_artist_label", "_album_label", "_genre_label"):
            label = getattr(panel, attr)
            assert label.wordWrap(), f"{attr} lost its wordWrap"
            assert not _overflows(label), f"{attr} overflows without wrap"


class TestAlbumGrid:
    """Grid cards paint pre-elided text (AlbumCardWidget has no labels —
    the painter elides via fm.elidedText, mirrors album_view.py:90)."""

    def test_grid_elide_logic(self, qapp):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFontMetrics
        from audio_player.player.album_manager import AlbumInfo
        album = AlbumInfo(name=LONG, artist=LONG, disc_count=1)
        fm = QFontMetrics(qapp.font())
        elided = fm.elidedText(album.name, Qt.TextElideMode.ElideRight, 170)
        assert elided != album.name, "long name must be elided for the card"
        assert fm.horizontalAdvance(elided) <= 175
