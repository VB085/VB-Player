import sys as _sys
from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, Qt, pyqtSignal, QThread, QObject
)
from PyQt6.QtGui import QIcon
from pathlib import Path

_MSYS2 = _sys.platform == "win32"  # QThread access violations on MSYS2 Python 3.14
from urllib.parse import urlparse
import random
import json
from enum import IntEnum
from queue import Queue

from .metadata import read_metadata, TrackMetadata

from audio_player.player._types import AUDIO_EXTENSIONS


def _is_url(path: str) -> bool:
    return path.startswith(("http://", "https://", "smb://"))


class RepeatMode(IntEnum):
    Off = 0
    All = 1
    One = 2


class _MetaLoader(QThread):
    """Single persistent thread for metadata loading. Queue-based, no repeated create/destroy."""
    loaded = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: Queue = Queue()
        self._running = True

    def enqueue(self, row: int, filepath: str):
        self._queue.put((row, filepath))
        if not self.isRunning():
            self.start()

    def run(self):
        while self._running:
            try:
                row, filepath = self._queue.get(timeout=1)
            except Exception:
                continue
            if not self._running:
                break
            try:
                meta = read_metadata(filepath)
            except Exception:
                meta = TrackMetadata()
            self.loaded.emit(row, meta)
            self.msleep(20)  # throttle — avoid flooding main thread with repaints

    def stop(self):
        self._running = False
        self._queue.put((-1, ""))  # unblock get()
        self.wait(3000)


class PlaylistManager(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 1
    ArtistRole = Qt.ItemDataRole.UserRole + 2
    AlbumRole = Qt.ItemDataRole.UserRole + 3
    DurationRole = Qt.ItemDataRole.UserRole + 4
    FilePathRole = Qt.ItemDataRole.UserRole + 5
    HasCoverRole = Qt.ItemDataRole.UserRole + 6
    MetadataReadyRole = Qt.ItemDataRole.UserRole + 7
    SourceTypeRole = Qt.ItemDataRole.UserRole + 8
    CoverDataRole = Qt.ItemDataRole.UserRole + 9

    currentIndexChanged = pyqtSignal(int)
    metadataLoaded = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks: list[dict] = []
        self._current_index = -1
        self._shuffle = False
        self._repeat = RepeatMode.Off
        self._shuffle_order: list[int] = []
        self._loader = None if _MSYS2 else _MetaLoader(self)
        if self._loader is not None:
            self._loader.loaded.connect(self._on_meta_loaded)

    def track_metadata(self, index: int):
        """Return cached TrackMetadata for row *index*, or None if not loaded yet."""
        if 0 <= index < len(self._tracks):
            return self._tracks[index].get("metadata")
        return None

    def shutdown(self):
        """Stop the metadata loader thread cleanly."""
        if self._loader is not None:
            self._loader.stop()

    def _on_meta_loaded(self, row: int, meta):
        """Receive metadata from loader thread, update model."""
        if 0 <= row < len(self._tracks):
            self._tracks[row]["metadata"] = meta
            self._tracks[row]["has_metadata"] = True
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [])
            self.metadataLoaded.emit(row, meta)

    def refresh_metadata_for(self, filepath: str):
        """Re-read metadata for a single file and update the model."""
        from audio_player.player.metadata import read_metadata
        for i, track in enumerate(self._tracks):
            if track["path"] == filepath:
                meta = read_metadata(filepath)
                self._tracks[i]["metadata"] = meta
                self._tracks[i]["has_metadata"] = True
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [])
                break

    @staticmethod
    def _display_name(track: dict) -> str:
        path = track["path"]
        if _is_url(path):
            parsed = urlparse(path)
            return parsed.hostname or path
        return Path(path).stem

    def rowCount(self, parent=QModelIndex()):
        return len(self._tracks)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._tracks):
            return None
        track = self._tracks[index.row()]
        meta = track.get("metadata")

        if role == Qt.ItemDataRole.DisplayRole:
            if meta:
                title = meta.title or self._display_name(track)
                artist = meta.artist or ""
                return f"{title} — {artist}" if artist else title
            return self._display_name(track)

        if role == self.TitleRole:
            return meta.title if meta else self._display_name(track)
        if role == self.ArtistRole:
            return meta.artist if meta else ""
        if role == self.AlbumRole:
            return meta.album if meta else ""
        if role == self.DurationRole:
            return meta.duration_seconds if meta else 0
        if role == self.FilePathRole:
            return track["path"]
        if role == self.HasCoverRole:
            return bool(meta and meta.cover_data)
        if role == self.CoverDataRole:
            return meta.cover_data if meta else None
        if role == self.MetadataReadyRole:
            return track.get("has_metadata", False)
        if role == self.SourceTypeRole:
            return track.get("source_type", "local")
        return None

    def add_files(self, paths: list[str]):
        start = len(self._tracks)
        for p in paths:
            if _is_url(p):
                self._tracks.append({"path": p, "source_type": "url", "has_metadata": False, "metadata": None})
            else:
                path = Path(p)
                if path.suffix.lower() in AUDIO_EXTENSIONS:
                    self._tracks.append({"path": str(path), "source_type": "local", "has_metadata": False, "metadata": None})
        if len(self._tracks) > start:
            self.beginResetModel()
            self.endResetModel()
            for i in range(start, len(self._tracks)):
                if self._tracks[i].get("source_type") != "url":
                    if self._loader is not None:
                        self._loader.enqueue(i, self._tracks[i]["path"])

    def add_url(self, url: str, title: str = None):
        """Add a single stream URL to the playlist."""
        row = len(self._tracks)
        meta = None
        if title:
            meta = TrackMetadata()
            meta.title = title
        self._tracks.append({"path": url, "source_type": "url", "has_metadata": bool(meta), "metadata": meta})
        self.beginResetModel()
        self.endResetModel()

    def add_urls(self, urls: list[str]):
        """Add multiple stream URLs to the playlist."""
        if not urls:
            return
        start = len(self._tracks)
        for url in urls:
            self._tracks.append({"path": url, "source_type": "url", "has_metadata": False, "metadata": None})
        if len(self._tracks) > start:
            self.beginResetModel()
            self.endResetModel()

    def insert_next(self, filepath: str):
        """Insert a single track right after the current playing index."""
        if _is_url(filepath):
            entry = {"path": filepath, "source_type": "url", "has_metadata": False, "metadata": None}
        else:
            p = Path(filepath)
            if p.suffix.lower() not in AUDIO_EXTENSIONS:
                return
            entry = {"path": str(p), "source_type": "local", "has_metadata": False, "metadata": None}
            filepath = str(p)

        pos = self._current_index + 1 if self._current_index >= 0 else len(self._tracks)
        if pos > len(self._tracks):
            pos = len(self._tracks)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self._tracks.insert(pos, entry)
        self.endInsertRows()

        # Update current_index if the inserted track is before it
        if pos <= self._current_index:
            self._current_index += 1

        if entry["source_type"] != "url":
            if self._loader is not None:
                self._loader.enqueue(pos, filepath)

    def add_folder(self, path: str):
        folder = Path(path)
        files = []
        for ext in AUDIO_EXTENSIONS:
            files.extend(str(p) for p in folder.rglob(f"*{ext}"))
        files.sort()
        self.add_files(files)

    def moveRows(self, source_parent, source_row, count, dest_parent, dest_child):
        """Qt drag-and-drop reorder: move *count* rows starting at *source_row*
        to *dest_child* (before insertion). Returns True on success."""
        if source_row == dest_child or source_row + 1 == dest_child:
            return False  # no-op
        if count != 1:
            return False
        if not (0 <= source_row < len(self._tracks)):
            return False
        if dest_child < 0 or dest_child > len(self._tracks):
            return False

        self.beginMoveRows(QModelIndex(), source_row, source_row,
                           QModelIndex(), dest_child)
        track = self._tracks.pop(source_row)
        # Adjust destination if source was before it
        if source_row < dest_child:
            dest_child -= 1
        self._tracks.insert(dest_child, track)
        # Update current_index
        if self._current_index == source_row:
            self._current_index = dest_child
        elif source_row < self._current_index <= dest_child:
            self._current_index -= 1
        elif dest_child <= self._current_index < source_row:
            self._current_index += 1
        self.endMoveRows()
        return True

    def remove_indices(self, indices: list[int]):
        for row in sorted(indices, reverse=True):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._tracks[row]
            self.endRemoveRows()
            if row == self._current_index:
                self._current_index = -1
            elif row < self._current_index:
                self._current_index -= 1

    def clear(self):
        self.beginResetModel()
        self._tracks.clear()
        self._current_index = -1
        self._shuffle_order.clear()
        self.endResetModel()

    @property
    def current_index(self):
        return self._current_index

    @current_index.setter
    def current_index(self, idx):
        if idx != self._current_index:
            old = self._current_index
            self._current_index = idx
            # Repaint old and new rows so playing indicator moves
            if 0 <= old < len(self._tracks):
                qi = self.index(old, 0)
                self.dataChanged.emit(qi, qi, [])
            if 0 <= idx < len(self._tracks):
                qi = self.index(idx, 0)
                self.dataChanged.emit(qi, qi, [])
            self.currentIndexChanged.emit(idx)

    @property
    def current_track_path(self) -> str | None:
        if 0 <= self._current_index < len(self._tracks):
            actual = self._effective_index(self._current_index)
            if 0 <= actual < len(self._tracks):
                return self._tracks[actual]["path"]
        return None

    def peek_next_path(self) -> str | None:
        """Return the path of the next track without advancing the index."""
        n = len(self._tracks)
        if n == 0:
            return None
        next_idx = self._current_index + 1
        if self._shuffle:
            if next_idx >= n:
                if self._repeat == RepeatMode.All:
                    next_idx = 0
                else:
                    return None
        else:
            if next_idx >= n:
                if self._repeat == RepeatMode.All:
                    next_idx = 0
                else:
                    return None
        actual = self._effective_index(next_idx)
        if 0 <= actual < n:
            return self._tracks[actual]["path"]
        return None

    @property
    def count(self):
        return len(self._tracks)

    def _effective_index(self, display_idx):
        if self._shuffle and self._shuffle_order:
            if 0 <= display_idx < len(self._shuffle_order):
                return self._shuffle_order[display_idx]
        return display_idx

    def _reshuffle(self):
        n = len(self._tracks)
        self._shuffle_order = list(range(n))
        random.shuffle(self._shuffle_order)
        if self._current_index >= 0 and self._current_index < n:
            current_track = self._effective_index(self._current_index)
            if current_track in self._shuffle_order:
                self._shuffle_order.remove(current_track)
                self._shuffle_order.insert(0, current_track)

    @property
    def shuffle(self):
        return self._shuffle

    @shuffle.setter
    def shuffle(self, enabled: bool):
        self._shuffle = enabled
        if enabled:
            self._reshuffle()

    @property
    def repeat(self):
        return self._repeat

    @repeat.setter
    def repeat(self, mode: RepeatMode):
        self._repeat = mode

    def advance(self) -> bool:
        """Returns False if no more tracks to play."""
        if self._repeat == RepeatMode.One:
            return bool(self._tracks)
        n = len(self._tracks)
        if n == 0:
            return False
        next_idx = self._current_index + 1
        if self._shuffle:
            if next_idx >= n:
                if self._repeat == RepeatMode.All:
                    self._reshuffle()
                    next_idx = 0
                else:
                    return False
        else:
            if next_idx >= n:
                if self._repeat == RepeatMode.All:
                    next_idx = 0
                else:
                    return False
        self.current_index = next_idx
        return True

    def previous(self) -> bool:
        n = len(self._tracks)
        if n == 0:
            return False
        prev_idx = self._current_index - 1
        if prev_idx < 0:
            if self._repeat == RepeatMode.All:
                prev_idx = n - 1
            else:
                prev_idx = 0
        self.current_index = prev_idx
        return True

    def save_m3u(self, path: str):
        lines = ["#EXTM3U"]
        for track in self._tracks:
            meta = track.get("metadata")
            if meta and meta.duration_seconds:
                lines.append(f"#EXTINF:{int(meta.duration_seconds)},{meta.title or ''}")
            lines.append(track["path"])
        Path(path).write_text("\n".join(lines), encoding="utf-8")

    def load_m3u(self, path: str):
        content = Path(path).read_text(encoding="utf-8")
        files = []
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                files.append(line)
        self.add_files(files)

    def move_row(self, from_row, to_row):
        if from_row == to_row:
            return
        if not (0 <= from_row < len(self._tracks) and 0 <= to_row < len(self._tracks)):
            return
        self.beginMoveRows(QModelIndex(), from_row, from_row, QModelIndex(),
                           to_row + 1 if to_row > from_row else to_row)
        track = self._tracks.pop(from_row)
        self._tracks.insert(to_row, track)
        self.endMoveRows()

    def track_at(self, row) -> dict | None:
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None
