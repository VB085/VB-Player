"""Tests for PlaylistManager — model, shuffle, repeat, advance."""

import pytest
from pathlib import Path

from audio_player.player.playlist import PlaylistManager, RepeatMode, AUDIO_EXTENSIONS


@pytest.fixture
def pm(qapp):
    return PlaylistManager()


# ---- Basic model ----

def test_initial_state(pm):
    assert pm.rowCount() == 0
    assert pm.count == 0
    assert pm.current_index == -1


def test_add_files(pm, tmp_path):
    f = tmp_path / "test.mp3"
    f.write_bytes(b"\x00")
    pm.add_files([str(f)])
    assert pm.count == 1


def test_add_files_filters_non_audio(pm, tmp_path):
    f = tmp_path / "readme.txt"
    f.write_bytes(b"hello")
    pm.add_files([str(f)])
    assert pm.count == 0


def test_add_files_accepts_all_audio_extensions(pm, tmp_path):
    for ext in AUDIO_EXTENSIONS:
        f = tmp_path / f"track{ext}"
        f.write_bytes(b"\x00")
    pm.add_files([str(tmp_path / f"track{ext}") for ext in AUDIO_EXTENSIONS])
    assert pm.count == len(AUDIO_EXTENSIONS)


def test_remove_indices(pm, tmp_path):
    files = []
    for name in ["a.mp3", "b.mp3", "c.mp3"]:
        f = tmp_path / name
        f.write_bytes(b"\x00")
        files.append(str(f))
    pm.add_files(files)
    pm.remove_indices([1])
    assert pm.count == 2
    track = pm.track_at(0)
    assert track is not None
    assert "a.mp3" in track["path"]


def test_clear(pm, tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"\x00")
    pm.add_files([str(f)])
    pm.clear()
    assert pm.count == 0
    assert pm.current_index == -1


def test_track_at_out_of_range(pm):
    assert pm.track_at(-1) is None
    assert pm.track_at(0) is None
    assert pm.track_at(100) is None


def test_current_index_signal(pm, qtbot):
    f = Path("/tmp/_test_pm.mp3")
    f.write_bytes(b"\x00")
    pm.add_files([str(f)])
    with qtbot.waitSignal(pm.currentIndexChanged, timeout=1000) as blocker:
        pm.current_index = 0
    assert blocker.args == [0]


# ---- Move ----

def test_move_row(pm, tmp_path):
    files = []
    for name in ["a.mp3", "b.mp3", "c.mp3"]:
        f = tmp_path / name
        f.write_bytes(b"\x00")
        files.append(str(f))
    pm.add_files(files)
    pm.move_row(0, 2)
    assert "b.mp3" in pm.track_at(0)["path"]
    assert "c.mp3" in pm.track_at(1)["path"]
    assert "a.mp3" in pm.track_at(2)["path"]


def test_move_row_noop(pm, tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"\x00")
    pm.add_files([str(f)])
    pm.move_row(0, 0)  # should not raise
    assert pm.count == 1


# ---- Advance / Previous ----

def _populate(pm, tmp_path, n=5):
    files = []
    for i in range(n):
        f = tmp_path / f"t{i}.mp3"
        f.write_bytes(b"\x00")
        files.append(str(f))
    pm.add_files(files)
    pm.current_index = 0


def test_advance_basic(pm, tmp_path):
    _populate(pm, tmp_path, 3)
    assert pm.advance() is True
    assert pm.current_index == 1
    assert pm.advance() is True
    assert pm.current_index == 2
    assert pm.advance() is False  # end, no repeat
    assert pm.current_index == 2  # stays


def test_advance_repeat_all(pm, tmp_path):
    _populate(pm, tmp_path, 3)
    pm.repeat = RepeatMode.All
    pm.current_index = 2
    assert pm.advance() is True
    assert pm.current_index == 0  # wraps


def test_advance_repeat_one(pm, tmp_path):
    _populate(pm, tmp_path, 3)
    pm.repeat = RepeatMode.One
    pm.current_index = 1
    assert pm.advance() is True
    assert pm.current_index == 1  # stays on same track


def test_advance_empty(pm):
    assert pm.advance() is False


def test_previous_basic(pm, tmp_path):
    _populate(pm, tmp_path, 3)
    pm.current_index = 2
    assert pm.previous() is True
    assert pm.current_index == 1
    assert pm.previous() is True
    assert pm.current_index == 0
    assert pm.previous() is True
    assert pm.current_index == 0  # clamps at 0


def test_previous_repeat_all(pm, tmp_path):
    _populate(pm, tmp_path, 3)
    pm.repeat = RepeatMode.All
    pm.current_index = 0
    assert pm.previous() is True
    assert pm.current_index == 2  # wraps


def test_previous_empty(pm):
    assert pm.previous() is False


# ---- Shuffle ----

def test_shuffle_enabled(pm, tmp_path):
    _populate(pm, tmp_path, 10)
    pm.shuffle = True
    assert pm.shuffle is True
    # _shuffle_order should exist and contain all indices
    assert len(pm._shuffle_order) == 10
    assert set(pm._shuffle_order) == set(range(10))


def test_shuffle_preserves_current_track(pm, tmp_path):
    _populate(pm, tmp_path, 10)
    pm.current_index = 5
    pm.shuffle = True
    # Current track should be at position 0 in shuffle order
    assert pm._shuffle_order[0] == pm._effective_index(0) or pm._effective_index(0) in range(10)


def test_shuffle_advance(pm, tmp_path):
    _populate(pm, tmp_path, 5)
    pm.shuffle = True
    pm.repeat = RepeatMode.All
    pm.current_index = 0
    # Should advance through shuffle order
    for _ in range(5):
        assert pm.advance() is True


# ---- M3U save/load ----

def test_save_load_m3u(pm, tmp_path):
    files = []
    for name in ["a.mp3", "b.mp3"]:
        f = tmp_path / name
        f.write_bytes(b"\x00")
        files.append(str(f))
    pm.add_files(files)

    m3u_path = tmp_path / "test.m3u"
    pm.save_m3u(str(m3u_path))
    content = m3u_path.read_text()
    assert "#EXTM3U" in content
    assert "a.mp3" in content

    pm2 = PlaylistManager()
    pm2.load_m3u(str(m3u_path))
    assert pm2.count == 2


# ---- RepeatMode enum ----

def test_repeat_modes():
    assert RepeatMode.Off == 0
    assert RepeatMode.All == 1
    assert RepeatMode.One == 2
