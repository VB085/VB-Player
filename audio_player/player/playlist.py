from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, Qt, pyqtSignal, QThreadPool, QRunnable, QObject
)
from PyQt6.QtGui import QIcon
from pathlib import Path
import random
import json
from enum import IntEnum

from .metadata import read_metadata, TrackMetadata

AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".opus",
                    ".aac", ".m4a", ".wma", ".alac", ".aiff",
                    ".ape", ".wv", ".mpc", ".spx", ".oga",
                    ".dsf", ".dff"}


class RepeatMode(IntEnum):
    Off = 0
    All = 1
    One = 2


class _MetadataWorker(QRunnable):
    def __init__(self, model, row, filepath):
        super().__init__()
        self.model = model
        self.row = row
        self.filepath = filepath

    def run(self):
        try:
            meta = read_metadata(self.filepath)
            self.model._metadata_ready(self.row, meta)
        except Exception:
            pass


class _MetadataSignalBridge(QObject):
    ready = pyqtSignal(int, object)


class PlaylistManager(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 1
    ArtistRole = Qt.ItemDataRole.UserRole + 2
    AlbumRole = Qt.ItemDataRole.UserRole + 3
    DurationRole = Qt.ItemDataRole.UserRole + 4
    FilePathRole = Qt.ItemDataRole.UserRole + 5
    HasCoverRole = Qt.ItemDataRole.UserRole + 6
    MetadataReadyRole = Qt.ItemDataRole.UserRole + 7

    currentIndexChanged = pyqtSignal(int)
    metadataLoaded = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks: list[dict] = []
        self._current_index = -1
        self._shuffle = False
        self._repeat = RepeatMode.Off
        self._shuffle_order: list[int] = []
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(4)
        self._bridge = _MetadataSignalBridge()
        self._bridge.ready.connect(self._on_metadata_ready)

    def _metadata_ready(self, row, meta):
        self._bridge.ready.emit(row, meta)

    def _on_metadata_ready(self, row, meta):
        if 0 <= row < len(self._tracks):
            self._tracks[row]["metadata"] = meta
            self._tracks[row]["has_metadata"] = True
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [])

    def rowCount(self, parent=QModelIndex()):
        return len(self._tracks)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._tracks):
            return None
        track = self._tracks[index.row()]
        meta = track.get("metadata")

        if role == Qt.ItemDataRole.DisplayRole:
            if meta:
                title = meta.title or Path(track["path"]).stem
                artist = meta.artist or "Unknown Artist"
                return f"{title} — {artist}"
            return Path(track["path"]).stem

        if role == self.TitleRole:
            return meta.title if meta else Path(track["path"]).stem
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
        if role == self.MetadataReadyRole:
            return track.get("has_metadata", False)
        return None

    def add_files(self, paths: list[str]):
        start = len(self._tracks)
        for p in paths:
            path = Path(p)
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                self._tracks.append({"path": str(path), "has_metadata": False, "metadata": None})
        if len(self._tracks) > start:
            self.insertRows(start, len(self._tracks) - start, QModelIndex())
            for i in range(start, len(self._tracks)):
                worker = _MetadataWorker(self, i - start, self._tracks[i]["path"])
                self._pool.start(worker)

    def add_folder(self, path: str):
        folder = Path(path)
        files = []
        for ext in AUDIO_EXTENSIONS:
            files.extend(str(p) for p in folder.rglob(f"*{ext}"))
        files.sort()
        self.add_files(files)

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
            self._current_index = idx
            self.currentIndexChanged.emit(idx)

    @property
    def current_track_path(self) -> str | None:
        if 0 <= self._current_index < len(self._tracks):
            actual = self._effective_index(self._current_index)
            if 0 <= actual < len(self._tracks):
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
