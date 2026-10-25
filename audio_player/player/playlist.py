import sys as _sys
from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, Qt, pyqtSignal, QThread, QObject
)
from PyQt6.QtGui import QIcon
from pathlib import Path

_MSYS2 = _sys.platform == "win32" and "MSC" not in _sys.version  # QThread bugs on MSYS2 only
from urllib.parse import urlparse
import random
import json
from enum import IntEnum
from queue import PriorityQueue
from itertools import count

from .metadata import read_metadata, TrackMetadata

from audio_player.player._types import AUDIO_EXTENSIONS


def _is_url(path: str) -> bool:
    return path.startswith(("http://", "https://", "smb://"))


class RepeatMode(IntEnum):
    Off = 0
    All = 1
    One = 2


class _MetaLoader(QThread):
    """Single persistent thread for metadata loading. Queue-based, no repeated create/destroy.

    Two priority classes: priority 0 (visible-region rows, jumped to the
    front) and priority 1 (background bulk load). Without this, scrolling to
    row 800 of a large playlist waited for every earlier row to load first —
    covers took tens of seconds to appear.
    """
    loaded = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: PriorityQueue = PriorityQueue()
        self._pending: set[int] = set()   # rows currently queued (dedupe)
        self._running = True
        self._seq = count()               # C-atomic — keeps FIFO within a class

    def enqueue(self, row: int, filepath: str, priority: int = 1):
        if not self._running or row in self._pending:
            return
        self._pending.add(row)
        self._queue.put((priority, next(self._seq), row, filepath))
        if not self.isRunning():
            self.start()

    def enqueue_priority(self, rows_paths: list):
        """Put (row, path) pairs at the front — the visible region after scroll."""
        for row, filepath in rows_paths:
            self.enqueue(row, filepath, priority=0)

    def run(self):
        while self._running:
            try:
                _prio, _seq, row, filepath = self._queue.get(timeout=1)
            except Exception:
                continue
            self._pending.discard(row)
            if not self._running:
                break
            try:
                # priority 0 (visible region) carries cover bytes; the bulk
                # pass skips them — covers arrive via prewarm/ensure_cover
                meta = read_metadata(filepath, load_cover=(_prio == 0))
            except Exception:
                meta = TrackMetadata()
            self.loaded.emit(row, meta)
            self.msleep(0)  # yield — repaints are coalesced by the flush timer

    def stop(self):
        self._running = False
        self._queue.put((0, next(self._seq), -1, ""))  # unblock get()
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
    loadProgress = pyqtSignal(int, int)   # (done, total) during bulk loads

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
        # coalesced repaints during bulk loads
        from PyQt6.QtCore import QTimer
        self._dirty_rows: list[int] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(80)
        self._flush_timer.timeout.connect(self._flush_dirty_rows)

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
        """Receive metadata from loader thread: store now, repaint batched."""
        if 0 <= row < len(self._tracks):
            self._tracks[row]["metadata"] = meta
            self._tracks[row]["has_metadata"] = True
            self._dirty_rows.append(row)
            if not self._flush_timer.isActive():
                self._flush_timer.start(80)

    _FLUSH_CHUNK = 150   # rows per repaint tick — a 1400-row single
                         # dataChanged once froze the GUI for 2.3 s

    def _flush_dirty_rows(self):
        """Coalesced repaint: one dataChanged per contiguous range (~12 Hz
        max regardless of loader speed), then progress."""
        if not self._dirty_rows:
            return
        rows = sorted(set(self._dirty_rows))
        self._dirty_rows.clear()
        if len(rows) > self._FLUSH_CHUNK:
            # keep the tail for the next tick — a single huge range repaint
            # stalls the main thread (and starves every timer behind it)
            self._dirty_rows = rows[self._FLUSH_CHUNK:]
            rows = rows[:self._FLUSH_CHUNK]
            self._flush_timer.start()
        start = prev = rows[0]
        for r in rows[1:]:
            if r == prev + 1:
                prev = r
                continue
            self.dataChanged.emit(self.index(start, 0), self.index(prev, 0), [])
            start = prev = r
        self.dataChanged.emit(self.index(start, 0), self.index(prev, 0), [])
        for r in rows:
            self.metadataLoaded.emit(r, self._tracks[r].get("metadata"))
        pending = sum(1 for t in self._tracks
                      if not t.get("is_url") and not t.get("has_metadata"))
        done = sum(1 for t in self._tracks if t.get("has_metadata"))
        self.loadProgress.emit(done, done + pending)

    def prioritize_rows(self, rows):
        """Jump *rows* to the front of the metadata queue (visible region)."""
        if self._loader is None or not rows:
            return
        pairs = []
        for r in rows:
            if 0 <= r < len(self._tracks) and not self._tracks[r].get("has_metadata"):
                pairs.append((r, self._tracks[r]["path"]))
        if pairs:
            self._loader.enqueue_priority(pairs)

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
                    else:
                        # MSYS2: load synchronously in main thread + emit signal
                        try:
                            meta = read_metadata(self._tracks[i]["path"])
                            self._tracks[i]["metadata"] = meta
                            self._tracks[i]["has_metadata"] = True
                            idx = self.index(i, 0)
                            self.dataChanged.emit(idx, idx, [])
                            self.metadataLoaded.emit(i, meta)
                        except Exception:
                            pass

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
            else:
                try:
                    meta = read_metadata(filepath)
                    self._tracks[pos]["metadata"] = meta
                    self._tracks[pos]["has_metadata"] = True
                    idx = self.index(pos, 0)
                    self.dataChanged.emit(idx, idx, [])
                    self.metadataLoaded.emit(pos, meta)
                except Exception:
                    pass

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
