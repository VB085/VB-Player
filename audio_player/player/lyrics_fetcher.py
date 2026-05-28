"""Online lyrics fetching orchestrator with session cache."""

from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import QObject, QThread, pyqtSignal, QSettings

from audio_player.player.audio_analyzer import LyricsLine
from audio_player.player.lrc_parser import parse_lrc, merge_translation
from audio_player.player.lyrics_provider import (
    LyricsProvider, LyricsResult, LRCLIBProvider, CustomAPIProvider,
)


class LyricsState(Enum):
    IDLE = "idle"
    LOADING = "loading"
    SUCCESS = "success"
    EMPTY = "empty"
    NETWORK_ERROR = "network_error"
    CONFIG_ERROR = "config_error"


class LyricsFetchWorker(QThread):
    """Background thread for fetching lyrics. Mirrors _DecoderWorker pattern."""

    finished = pyqtSignal(object)  # LyricsResult | None
    error = pyqtSignal(str)

    def __init__(self, providers: list[LyricsProvider], title: str,
                 artist: str, duration_sec: float, timeout: float = 10.0):
        super().__init__()
        self._providers = providers
        self._title = title
        self._artist = artist
        self._duration_sec = duration_sec
        self._timeout = timeout

    def run(self) -> None:
        for provider in self._providers:
            try:
                result = provider.search(
                    self._title, self._artist,
                    self._duration_sec, self._timeout,
                )
                if result is not None:
                    self.finished.emit(result)
                    return
            except Exception as e:
                self.error.emit(str(e))
                continue
        self.finished.emit(None)


class LyricsFetcher(QObject):
    """Orchestrates online lyrics fetching with session cache."""

    stateChanged = pyqtSignal(object)  # LyricsState enum object
    lyricsReady = pyqtSignal(object)   # list[LyricsLine]

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._cache: dict[tuple[str, str], list[LyricsLine]] = {}
        self._worker: LyricsFetchWorker | None = None
        self._request_id = 0
        self._state = LyricsState.IDLE
        self._providers: list[LyricsProvider] = []
        self._current_artist = ""
        self._current_title = ""

    def configure(self, online_enabled: bool, lrclib_enabled: bool,
                  custom_url: str = "", custom_token: str = "") -> None:
        """Rebuild provider list from settings."""
        self._providers.clear()
        if not online_enabled:
            return
        if lrclib_enabled:
            self._providers.append(LRCLIBProvider())
        if custom_url:
            self._providers.append(CustomAPIProvider(custom_url, custom_token))

    @property
    def state(self) -> LyricsState:
        return self._state

    def fetch(self, title: str, artist: str, duration_sec: float) -> None:
        """Start async fetch. Results come via lyricsReady signal."""
        cache_key = (self._normalize(artist), self._normalize(title))
        if cache_key in self._cache:
            self._set_state(LyricsState.SUCCESS)
            self.lyricsReady.emit(self._cache[cache_key])
            return

        if not self._providers:
            self._set_state(LyricsState.CONFIG_ERROR)
            self.lyricsReady.emit([])
            return

        self._request_id += 1
        req_id = self._request_id
        self._cancel_worker()

        self._current_artist = artist
        self._current_title = title
        self._set_state(LyricsState.LOADING)
        self._worker = LyricsFetchWorker(
            self._providers, title, artist, duration_sec,
        )
        self._worker.finished.connect(lambda r: self._on_finished(r, req_id))
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, result: LyricsResult | None, req_id: int) -> None:
        if req_id != self._request_id:
            return  # stale response, discard

        self._cleanup_worker()

        if result is None:
            self._set_state(LyricsState.EMPTY)
            self.lyricsReady.emit([])
            return

        lines = parse_lrc(result.synced_lyrics)
        if result.translated_lyrics:
            s = QSettings("VBPlayer", "VB Player")
            show_trans = str(s.value("show_translation", "true")).lower() == "true"
            if show_trans:
                merge_translation(lines, result.translated_lyrics)

        # Cache the result
        cache_key = (self._normalize(self._current_artist),
                     self._normalize(self._current_title))
        self._cache[cache_key] = lines
        self._set_state(LyricsState.SUCCESS)
        self.lyricsReady.emit(lines)

    def _on_error(self, msg: str) -> None:
        self._set_state(LyricsState.NETWORK_ERROR)

    def _set_state(self, state: LyricsState) -> None:
        self._state = state
        self.stateChanged.emit(state)

    def cleanup(self) -> None:
        """Stop any running worker. Call before application exit."""
        if self._worker and self._worker.isRunning():
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except TypeError:
                pass
            self._worker.quit()
            self._worker.wait(2000)
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    def _cancel_worker(self) -> None:
        if self._worker and self._worker.isRunning():
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except TypeError:
                pass
            self._worker.quit()
            self._worker.wait(1000)
            self._worker.deleteLater()
            self._worker = None

    def _cleanup_worker(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    def cache_result(self, artist: str, title: str,
                     lines: list[LyricsLine]) -> None:
        """Store a result in session cache."""
        cache_key = (self._normalize(artist), self._normalize(title))
        self._cache[cache_key] = lines

    @staticmethod
    def _normalize(s: str) -> str:
        return s.strip().lower()
