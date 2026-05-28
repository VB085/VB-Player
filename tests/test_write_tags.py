"""Tests for write_tags — metadata write-back via mutagen."""

import pytest
from pathlib import Path

from audio_player.player.metadata import read_metadata, write_tags, _evict_cache, _metadata_cache


def _make_test_mp3(path: Path) -> Path:
    """Create a valid MP3 file with ID3v2 tags for testing."""
    pytest.importorskip("mutagen")
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, ID3NoHeaderError

    # Write empty ID3 header + valid MPEG1 Layer3 frames
    # (mutagen needs valid MPEG sync words after the ID3 tag)
    with open(path, 'wb') as f:
        f.write(b'ID3\x03\x00\x00\x00\x00\x00\x00')  # empty ID3v2.3 header
        # MPEG1 Layer3 128kbps 44100Hz stereo frame: 0xFFFB9004 + 413 bytes padding
        frame = b'\xff\xfb\x90\x04' + b'\x00' * 413
        for _ in range(20):
            f.write(frame)

    # Add ID3 tags
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=["Original Title"]))
    tags.add(TPE1(encoding=3, text=["Original Artist"]))
    tags.add(TALB(encoding=3, text=["Original Album"]))
    tags.save(str(path))
    return path


class TestWriteTagsMP3:
    """Test write_tags with MP3/ID3 format."""

    def test_write_title(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {"title": "New Title"})
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.title == "New Title"

    def test_write_multiple_fields(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {
            "title": "New Title",
            "artist": "New Artist",
            "album": "New Album",
            "year": 2025,
            "genre": "Rock",
        })
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.title == "New Title"
        assert meta.artist == "New Artist"
        assert meta.album == "New Album"
        assert meta.year == 2025
        assert meta.genre == "Rock"

    def test_write_track_number(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {"track_number": 5})
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.track_number == 5

    def test_write_disc_number(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {"disc_number": 2})
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.disc_number == 2

    def test_clear_field(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {"artist": ""})
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.artist == ""

    def test_preserve_untouched_fields(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {"title": "Changed"})
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.title == "Changed"
        assert meta.artist == "Original Artist"
        assert meta.album == "Original Album"

    def test_none_clears_field(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {"genre": None})
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.genre == ""

    def test_write_all_fields(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        write_tags(str(path), {
            "title": "T", "artist": "A", "album": "Al",
            "album_artist": "AA", "year": 2020, "genre": "G",
            "track_number": 7, "disc_number": 2,
        })
        _evict_cache(str(path))
        meta = read_metadata(str(path))
        assert meta.title == "T"
        assert meta.artist == "A"
        assert meta.album == "Al"
        assert meta.album_artist == "AA"
        assert meta.year == 2020
        assert meta.genre == "G"
        assert meta.track_number == 7
        assert meta.disc_number == 2


class TestWriteTagsErrors:
    """Test write_tags error handling."""

    def test_unsupported_format(self, tmp_path):
        path = tmp_path / "test.txt"
        path.write_text("not audio")
        with pytest.raises(ValueError, match="Unsupported"):
            write_tags(str(path), {"title": "Test"})

    def test_nonexistent_file(self):
        with pytest.raises(Exception):
            write_tags("/nonexistent/file.mp3", {"title": "Test"})


class TestEvictCache:
    """Test cache eviction."""

    def test_evict_existing(self, tmp_path):
        path = _make_test_mp3(tmp_path / "test.mp3")
        read_metadata(str(path))
        assert str(path) in _metadata_cache
        _evict_cache(str(path))
        assert str(path) not in _metadata_cache

    def test_evict_nonexistent(self):
        _evict_cache("/nonexistent/file.mp3")  # should not raise
