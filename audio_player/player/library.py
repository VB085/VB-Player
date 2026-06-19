"""Persistent library: favorites + named playlists + watch folders + album cache. JSON-backed."""

import json
import os
import sys
import tempfile
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QThread


from audio_player.player._types import AUDIO_EXTENSIONS as _AUDIO_EXTENSIONS


def _library_path() -> Path:
    d = Path.home() / ".config" / "VBPlayer"
    d.mkdir(parents=True, exist_ok=True)
    return d / "library.json"


class _ScanWorker(QThread):
    """Background thread for scanning watch folders."""
    finished = pyqtSignal(list)  # list of file paths

    def __init__(self, watch_folders: list[str], parent=None):
        super().__init__(parent)
        self._watch_folders = watch_folders

    def run(self):
        found: set[str] = set()
        for folder in self._watch_folders:
            p = Path(folder)
            if not p.is_dir():
                continue
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS:
                    found.add(str(f))
        self.finished.emit(sorted(found))


AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".opus",
                    ".aac", ".m4a", ".wma", ".alac", ".aiff",
                    ".ape", ".wv", ".mpc", ".spx", ".oga",
                    ".dsf", ".dff", ".aac"}


class LibraryManager(QObject):
    favoritesChanged = pyqtSignal()
    playlistsChanged = pyqtSignal()
    scanFinished = pyqtSignal(list)  # async scan result

    def __init__(self, parent=None):
        super().__init__(parent)
        self._favorites: set[str] = set()
        self._playlists: dict[str, list[str]] = {}
        self._playlist_meta: dict[str, dict] = {}
        self._watch_folders: list[str] = []
        self._album_cache: dict = {}
        self._load()

    # ---- Persistence ----

    def _load(self):
        p = _library_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[library] JSON 解析错误，文件可能损坏: {p} — {e}", file=sys.stderr)
            return
        except OSError as e:
            print(f"[library] 读取失败: {p} — {e}", file=sys.stderr)
            return
        self._favorites = set(data.get("favorites", []))
        self._playlists = data.get("playlists", {})
        self._playlist_meta = data.get("playlist_meta", {})
        self._watch_folders = data.get("watch_folders", [])
        self._album_cache = data.get("album_cache", {})

    def _save(self):
        p = _library_path()
        data = {
            "favorites": sorted(self._favorites),
            "playlists": self._playlists,
            "playlist_meta": self._playlist_meta,
            "watch_folders": self._watch_folders,
            "album_cache": self._album_cache,
        }
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            # Atomic write: write to temp file then rename
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                Path(tmp).replace(p)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as e:
            print(f"[library] 保存失败 (数据未丢失，仍在内存中): {p} — {e}", file=sys.stderr)

    # ---- Favorites ----

    def is_favorite(self, path: str) -> bool:
        return path in self._favorites

    def toggle_favorite(self, path: str) -> bool:
        if path in self._favorites:
            self._favorites.discard(path)
            self._save()
            self.favoritesChanged.emit()
            return False
        else:
            self._favorites.add(path)
            self._save()
            self.favoritesChanged.emit()
            return True

    def add_to_favorites(self, paths: list[str]):
        for p in paths:
            self._favorites.add(p)
        self._save()
        self.favoritesChanged.emit()

    def remove_from_favorites(self, paths: list[str]):
        for p in paths:
            self._favorites.discard(p)
        self._save()
        self.favoritesChanged.emit()

    def get_favorites(self) -> list[str]:
        return sorted(self._favorites)

    def favorite_count(self) -> int:
        return len(self._favorites)

    # ---- Playlists ----

    def create_playlist(self, name: str) -> bool:
        if name in self._playlists:
            return False
        self._playlists[name] = []
        self._save()
        self.playlistsChanged.emit()
        return True

    def delete_playlist(self, name: str):
        if name in self._playlists:
            del self._playlists[name]
            self._playlist_meta.pop(name, None)
            self._save()
            self.playlistsChanged.emit()

    def rename_playlist(self, old: str, new: str) -> bool:
        if old not in self._playlists or new in self._playlists:
            return False
        self._playlists[new] = self._playlists.pop(old)
        if old in self._playlist_meta:
            self._playlist_meta[new] = self._playlist_meta.pop(old)
        self._save()
        self.playlistsChanged.emit()
        return True

    def get_playlist_names(self) -> list[str]:
        return sorted(self._playlists.keys())

    def get_playlist_tracks(self, name: str) -> list[str]:
        return list(self._playlists.get(name, []))

    def playlist_track_count(self, name: str) -> int:
        return len(self._playlists.get(name, []))

    def add_to_playlist(self, name: str, paths: list[str]):
        if name not in self._playlists:
            self._playlists[name] = []
        existing = set(self._playlists[name])
        for p in paths:
            if p not in existing:
                self._playlists[name].append(p)
                existing.add(p)
        self._save()
        self.playlistsChanged.emit()

    def remove_from_playlist(self, name: str, indices: list[int]):
        if name not in self._playlists:
            return
        tracks = self._playlists[name]
        for i in sorted(indices, reverse=True):
            if 0 <= i < len(tracks):
                tracks.pop(i)
        self._save()
        self.playlistsChanged.emit()

    def playlist_exists(self, name: str) -> bool:
        return name in self._playlists

    # ---- Playlist Meta (description, custom cover) ----

    def get_playlist_meta(self, name: str) -> dict:
        return self._playlist_meta.get(name, {"description": "", "cover_path": ""})

    def update_playlist_meta(self, name: str, description: str | None = None, cover_path: str | None = None):
        if name not in self._playlists:
            return
        meta = self._playlist_meta.setdefault(name, {"description": "", "cover_path": ""})
        if description is not None:
            meta["description"] = description
        if cover_path is not None:
            meta["cover_path"] = cover_path
        self._save()

    # ---- Watch Folders ----

    def get_watch_folders(self) -> list[str]:
        return list(self._watch_folders)

    def set_watch_folders(self, folders: list[str]):
        self._watch_folders = list(folders)
        self._save()

    def add_watch_folder(self, folder: str):
        if folder not in self._watch_folders:
            self._watch_folders.append(folder)
            self._save()

    def remove_watch_folder(self, folder: str):
        if folder in self._watch_folders:
            self._watch_folders.remove(folder)
            self._save()

    def scan_watch_folders(self) -> list[str]:
        """Scan all watch folders and return sorted list of audio file paths."""
        found: set[str] = set()
        for folder in self._watch_folders:
            p = Path(folder)
            if not p.is_dir():
                continue
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS:
                    found.add(str(f))
        return sorted(found)

    def scan_watch_folders_async(self):
        """Scan watch folders in a background thread, emit scanFinished when done."""
        if not self._watch_folders:
            self.scanFinished.emit([])
            return
        worker = _ScanWorker(self._watch_folders, self)
        worker.finished.connect(self._on_scan_finished)
        # Store ref to prevent garbage collection
        self._scan_worker = worker
        worker.start()

    def _on_scan_finished(self, paths: list[str]):
        if self._scan_worker:
            self._scan_worker.deleteLater()
            self._scan_worker = None
        self.scanFinished.emit(paths)

    # ---- Album Cache ----

    def get_album_cache(self) -> dict:
        return self._album_cache

    def set_album_cache(self, cache: dict):
        self._album_cache = cache
        self._save()

    def clear_album_cache(self):
        self._album_cache = {}
        self._save()
