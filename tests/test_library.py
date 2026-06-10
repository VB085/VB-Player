"""Tests for LibraryManager — favorites, playlists, persistence."""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from audio_player.player.library import LibraryManager


@pytest.fixture
def lib(qapp, tmp_path):
    """Create a LibraryManager backed by a temp file."""
    lib_path = tmp_path / "library.json"
    with patch("audio_player.player.library._library_path", return_value=lib_path):
        mgr = LibraryManager()
        yield mgr, lib_path


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---- Favorites ----

def test_initial_favorites_empty(lib):
    mgr, _ = lib
    assert mgr.get_favorites() == []
    assert mgr.favorite_count() == 0


def test_is_favorite_false_by_default(lib):
    mgr, _ = lib
    assert mgr.is_favorite("/some/path.mp3") is False


def test_toggle_favorite_adds(lib):
    mgr, _ = lib
    result = mgr.toggle_favorite("/a.mp3")
    assert result is True
    assert mgr.is_favorite("/a.mp3") is True
    assert mgr.favorite_count() == 1


def test_toggle_favorite_removes(lib):
    mgr, _ = lib
    mgr.toggle_favorite("/a.mp3")
    result = mgr.toggle_favorite("/a.mp3")
    assert result is False
    assert mgr.is_favorite("/a.mp3") is False
    assert mgr.favorite_count() == 0


def test_add_to_favorites(lib):
    mgr, _ = lib
    mgr.add_to_favorites(["/a.mp3", "/b.mp3"])
    assert mgr.favorite_count() == 2
    assert mgr.is_favorite("/a.mp3") is True
    assert mgr.is_favorite("/b.mp3") is True


def test_add_to_favorites_dedup(lib):
    mgr, _ = lib
    mgr.add_to_favorites(["/a.mp3", "/a.mp3"])
    assert mgr.favorite_count() == 1


def test_remove_from_favorites(lib):
    mgr, _ = lib
    mgr.add_to_favorites(["/a.mp3", "/b.mp3"])
    mgr.remove_from_favorites(["/a.mp3"])
    assert mgr.favorite_count() == 1
    assert mgr.is_favorite("/a.mp3") is False
    assert mgr.is_favorite("/b.mp3") is True


def test_get_favorites_sorted(lib):
    mgr, _ = lib
    mgr.add_to_favorites(["/c.mp3", "/a.mp3", "/b.mp3"])
    assert mgr.get_favorites() == ["/a.mp3", "/b.mp3", "/c.mp3"]


# ---- Playlists ----

def test_create_playlist(lib):
    mgr, _ = lib
    assert mgr.create_playlist("My List") is True
    assert "My List" in mgr.get_playlist_names()


def test_create_playlist_duplicate(lib):
    mgr, _ = lib
    mgr.create_playlist("My List")
    assert mgr.create_playlist("My List") is False


def test_delete_playlist(lib):
    mgr, _ = lib
    mgr.create_playlist("My List")
    mgr.delete_playlist("My List")
    assert mgr.get_playlist_names() == []


def test_delete_playlist_nonexistent(lib):
    mgr, _ = lib
    mgr.delete_playlist("Nope")  # should not raise


def test_rename_playlist(lib):
    mgr, _ = lib
    mgr.create_playlist("Old")
    assert mgr.rename_playlist("Old", "New") is True
    assert "New" in mgr.get_playlist_names()
    assert "Old" not in mgr.get_playlist_names()


def test_rename_playlist_target_exists(lib):
    mgr, _ = lib
    mgr.create_playlist("A")
    mgr.create_playlist("B")
    assert mgr.rename_playlist("A", "B") is False


def test_rename_playlist_source_missing(lib):
    mgr, _ = lib
    assert mgr.rename_playlist("Nope", "New") is False


def test_add_to_playlist(lib):
    mgr, _ = lib
    mgr.create_playlist("P")
    mgr.add_to_playlist("P", ["/a.mp3", "/b.mp3"])
    assert mgr.get_playlist_tracks("P") == ["/a.mp3", "/b.mp3"]
    assert mgr.playlist_track_count("P") == 2


def test_add_to_playlist_auto_creates(lib):
    mgr, _ = lib
    mgr.add_to_playlist("New", ["/a.mp3"])
    assert mgr.playlist_exists("New")
    assert mgr.get_playlist_tracks("New") == ["/a.mp3"]


def test_add_to_playlist_dedup(lib):
    mgr, _ = lib
    mgr.create_playlist("P")
    mgr.add_to_playlist("P", ["/a.mp3"])
    mgr.add_to_playlist("P", ["/a.mp3", "/b.mp3"])
    assert mgr.get_playlist_tracks("P") == ["/a.mp3", "/b.mp3"]


def test_remove_from_playlist(lib):
    mgr, _ = lib
    mgr.create_playlist("P")
    mgr.add_to_playlist("P", ["/a.mp3", "/b.mp3", "/c.mp3"])
    mgr.remove_from_playlist("P", [1])  # remove /b.mp3
    assert mgr.get_playlist_tracks("P") == ["/a.mp3", "/c.mp3"]


def test_remove_from_playlist_nonexistent(lib):
    mgr, _ = lib
    mgr.remove_from_playlist("Nope", [0])  # should not raise


def test_playlist_track_count_empty(lib):
    mgr, _ = lib
    assert mgr.playlist_track_count("Nope") == 0


# ---- Playlist Meta ----

def test_playlist_meta_default(lib):
    mgr, _ = lib
    meta = mgr.get_playlist_meta("Nope")
    assert meta == {"description": "", "cover_path": ""}


def test_update_playlist_meta(lib):
    mgr, _ = lib
    mgr.create_playlist("P")
    mgr.update_playlist_meta("P", description="desc", cover_path="/cover.jpg")
    meta = mgr.get_playlist_meta("P")
    assert meta["description"] == "desc"
    assert meta["cover_path"] == "/cover.jpg"


def test_update_playlist_meta_partial(lib):
    mgr, _ = lib
    mgr.create_playlist("P")
    mgr.update_playlist_meta("P", description="desc")
    mgr.update_playlist_meta("P", cover_path="/c.jpg")
    meta = mgr.get_playlist_meta("P")
    assert meta["description"] == "desc"
    assert meta["cover_path"] == "/c.jpg"


def test_rename_playlist_moves_meta(lib):
    mgr, _ = lib
    mgr.create_playlist("P")
    mgr.update_playlist_meta("P", description="hello")
    mgr.rename_playlist("P", "Q")
    assert mgr.get_playlist_meta("Q")["description"] == "hello"


# ---- Persistence ----

def test_favorites_persist(lib):
    mgr, path = lib
    mgr.add_to_favorites(["/a.mp3", "/b.mp3"])

    with patch("audio_player.player.library._library_path", return_value=path):
        mgr2 = LibraryManager()
    assert mgr2.get_favorites() == ["/a.mp3", "/b.mp3"]


def test_playlists_persist(lib):
    mgr, path = lib
    mgr.create_playlist("P")
    mgr.add_to_playlist("P", ["/a.mp3"])

    with patch("audio_player.player.library._library_path", return_value=path):
        mgr2 = LibraryManager()
    assert mgr2.get_playlist_tracks("P") == ["/a.mp3"]


def test_corrupt_json_handled(lib, tmp_path):
    mgr, path = lib
    path.write_text("not json", encoding="utf-8")
    with patch("audio_player.player.library._library_path", return_value=path):
        mgr2 = LibraryManager()  # should not raise
    assert mgr2.get_favorites() == []
