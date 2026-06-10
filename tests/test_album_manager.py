"""Tests for AlbumManager — grouping tracks into albums."""

import pytest
from unittest.mock import patch, MagicMock

from audio_player.player.album_manager import AlbumManager, AlbumInfo
from audio_player.player.metadata import TrackMetadata


def _make_track(path, **meta_kwargs):
    """Build a track dict with optional metadata override."""
    t = {"path": path, "has_metadata": False, "metadata": None}
    if meta_kwargs:
        t["metadata"] = TrackMetadata(**meta_kwargs)
        t["has_metadata"] = True
    return t


@pytest.fixture
def am():
    return AlbumManager()


def test_empty_tracks(am):
    assert am.group_by_album([]) == []


def test_single_track_with_album(am):
    tracks = [_make_track("/a.mp3", album="Test Album", artist="Artist")]
    albums = am.group_by_album(tracks)
    assert len(albums) == 1
    assert albums[0].name == "Test Album"
    assert albums[0].artist == "Artist"
    assert albums[0].track_count == 1


def test_multiple_tracks_same_album(am):
    tracks = [
        _make_track("/a.mp3", album="Album A", artist="X", track_number=1),
        _make_track("/b.mp3", album="Album A", artist="X", track_number=2),
    ]
    albums = am.group_by_album(tracks)
    assert len(albums) == 1
    assert albums[0].track_count == 2
    assert albums[0].tracks == [(0, "/a.mp3"), (1, "/b.mp3")]


def test_different_albums(am):
    tracks = [
        _make_track("/a.mp3", album="Album A", artist="X"),
        _make_track("/b.mp3", album="Album B", artist="Y"),
    ]
    albums = am.group_by_album(tracks)
    assert len(albums) == 2
    names = {a.name for a in albums}
    assert names == {"Album A", "Album B"}


def test_folder_fallback_no_album(am):
    tracks = [_make_track("/music/songs/track.mp3")]
    albums = am.group_by_album(tracks)
    assert len(albums) == 1
    assert albums[0].name == "songs"  # parent folder name


def test_tracks_sorted_by_disc_then_track(am):
    tracks = [
        _make_track("/b.mp3", album="A", disc_number=1, track_number=2),
        _make_track("/a.mp3", album="A", disc_number=1, track_number=1),
        _make_track("/c.mp3", album="A", disc_number=2, track_number=1),
    ]
    albums = am.group_by_album(tracks)
    assert len(albums) == 1
    indices = [idx for idx, _ in albums[0].tracks]
    assert indices == [1, 0, 2]  # sorted: (1,1), (1,2), (2,1)


def test_disc_count(am):
    tracks = [
        _make_track("/a.mp3", album="A", disc_number=1),
        _make_track("/b.mp3", album="A", disc_number=2),
        _make_track("/c.mp3", album="A", disc_number=1),
    ]
    albums = am.group_by_album(tracks)
    assert albums[0].disc_count == 2


def test_total_duration(am):
    tracks = [
        _make_track("/a.mp3", album="A", duration_seconds=180.5),
        _make_track("/b.mp3", album="A", duration_seconds=240.0),
    ]
    albums = am.group_by_album(tracks)
    assert abs(albums[0].total_duration - 420.5) < 0.01


def test_formats_collected(am):
    tracks = [
        _make_track("/a.mp3", album="A", format="MP3"),
        _make_track("/b.flac", album="A", format="FLAC"),
    ]
    albums = am.group_by_album(tracks)
    assert "FLAC" in albums[0].formats
    assert "MP3" in albums[0].formats


def test_cover_from_first_track(am):
    tracks = [
        _make_track("/a.mp3", album="A", cover_data=b"\x89PNG"),
        _make_track("/b.mp3", album="A"),
    ]
    albums = am.group_by_album(tracks)
    assert albums[0].cover_data == b"\x89PNG"


def test_year_from_first_track(am):
    tracks = [
        _make_track("/a.mp3", album="A", year=2020),
        _make_track("/b.mp3", album="A", year=2021),
    ]
    albums = am.group_by_album(tracks)
    assert albums[0].year == 2020  # first non-None


def test_albums_sorted_by_name(am):
    tracks = [
        _make_track("/b.mp3", album="Zebra"),
        _make_track("/a.mp3", album="Apple"),
    ]
    albums = am.group_by_album(tracks)
    assert [a.name for a in albums] == ["Apple", "Zebra"]


def test_total_size(am):
    tracks = [
        _make_track("/a.mp3", album="A", file_size=1000),
        _make_track("/b.mp3", album="A", file_size=2000),
    ]
    albums = am.group_by_album(tracks)
    assert albums[0].total_size == 3000


@patch("audio_player.player.metadata.read_metadata")
def test_reads_metadata_when_missing(mock_read, am):
    mock_read.return_value = TrackMetadata(album="FromDisk", artist="X")
    tracks = [{"path": "/a.mp3", "has_metadata": False, "metadata": None}]
    albums = am.group_by_album(tracks)
    mock_read.assert_called_once_with("/a.mp3")
    assert albums[0].name == "FromDisk"
