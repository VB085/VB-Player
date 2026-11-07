"""Online provider page: search, provider playlists, results and online queue."""

from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from audio_player.i18n import _
from audio_player.player.online import OnlineProvider
from audio_player.player.playlist import PlaylistManager
from audio_player.ui.widgets.playlist_view import PlaylistView


class OnlinePage(QWidget):
    """Provider-driven online library, isolated from the local playlist."""

    playResultsRequested = pyqtSignal(list, int)   # items, start index
    queuePlayRequested = pyqtSignal(int)

    _searchDone = pyqtSignal(int, list, str)
    _resultsDone = pyqtSignal(list, str)
    _playlistsDone = pyqtSignal(list, str)
    _recommendDone = pyqtSignal(str, list, str)
    _qualityDone = pyqtSignal(str, str)

    def __init__(self, online_playlist: PlaylistManager, parent=None):
        super().__init__(parent)
        self.setObjectName("onlinePage")
        self._provider: OnlineProvider | None = None
        self._provider_base = ""
        self._provider_healthy = False
        self._queue = online_playlist
        self._results_items: list[tuple[str, dict]] = []
        self._search_id = 0
        self._last_recommend = ""

        self._results_model = PlaylistManager(self)
        self._build_ui()

        self._searchDone.connect(self._on_search_done)
        self._resultsDone.connect(self._on_results_done)
        self._playlistsDone.connect(self._on_playlists_done)
        self._recommendDone.connect(self._on_recommend_done)
        self._qualityDone.connect(self._on_quality_done)

        self.set_online_playlist(online_playlist)
        self._set_enabled(False)

    # ------------------------------------------------------------------
    #  UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 0)
        self._title = QLabel(_("online.title"))
        self._title.setObjectName("pageTitle")
        header.addWidget(self._title)
        self._provider_label = QLabel(_("online.no_provider"))
        self._provider_label.setObjectName("networkSectionLabel")
        header.addWidget(self._provider_label, 1)
        self._refresh_btn = QPushButton(_("online.refresh"))
        self._refresh_btn.setObjectName("networkPlayBtn")
        self._refresh_btn.clicked.connect(self._refresh_playlists)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        controls = QHBoxLayout()
        controls.setContentsMargins(12, 0, 12, 0)
        self._search_input = QLineEdit()
        self._search_input.setObjectName("onlineSearchInput")
        self._search_input.setPlaceholderText(_("online.search_placeholder"))
        self._search_input.returnPressed.connect(self._on_search)
        controls.addWidget(self._search_input, 1)
        self._search_btn = QPushButton(_("online.search"))
        self._search_btn.setObjectName("networkPlayBtn")
        self._search_btn.clicked.connect(self._on_search)
        controls.addWidget(self._search_btn)

        self._quality_combo = QComboBox()
        self._quality_combo.setObjectName("onlineQualityCombo")
        for qid, key in (
            ("auto", "online.quality_auto"),
            ("standard", "online.quality_standard"),
            ("hq", "online.quality_hq"),
            ("sq", "online.quality_sq"),
            ("hires", "online.quality_hires"),
        ):
            self._quality_combo.addItem(_(key), qid)
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        controls.addWidget(self._quality_combo)
        layout.addLayout(controls)

        library_row = QHBoxLayout()
        library_row.setContentsMargins(12, 0, 12, 0)
        self._playlist_combo = QComboBox()
        self._playlist_combo.setObjectName("onlinePlaylistCombo")
        self._playlist_combo.setMinimumWidth(200)
        self._playlist_combo.activated.connect(self._on_playlist_changed)
        library_row.addWidget(self._playlist_combo, 1)

        self._recommend_combo = QComboBox()
        self._recommend_combo.setObjectName("onlineRecommendCombo")
        self._recommend_combo.addItem(_("online.select_recommend"), "")
        self._recommend_combo.addItem(_("online.recommend_daily"), "daily")
        self._recommend_combo.addItem(_("online.recommend_radio"), "radio")
        self._recommend_combo.addItem(_("online.recommend_radar"), "radar")
        self._recommend_combo.activated.connect(self._on_recommend_changed)
        library_row.addWidget(self._recommend_combo)

        self._refresh_batch_btn = QPushButton(_("online.refresh_batch"))
        self._refresh_batch_btn.setObjectName("networkPlayBtn")
        self._refresh_batch_btn.clicked.connect(self._refresh_batch)
        library_row.addWidget(self._refresh_batch_btn)

        self._play_all_btn = QPushButton(_("online.play_all"))
        self._play_all_btn.setObjectName("networkPlayBtn")
        self._play_all_btn.clicked.connect(self._play_all)
        library_row.addWidget(self._play_all_btn)
        layout.addLayout(library_row)

        self._status = QLabel("")
        self._status.setObjectName("networkSectionLabel")
        self._status.setContentsMargins(12, 0, 12, 0)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setContentsMargins(12, 0, 12, 12)

        results_box = QWidget()
        results_layout = QVBoxLayout(results_box)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_label = QLabel(_("online.results"))
        results_label.setObjectName("networkSectionLabel")
        results_layout.addWidget(results_label)
        self._results_view = PlaylistView(context_menu_enabled=False)
        self._results_view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self._results_view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._results_view.setModel(self._results_model)
        self._results_view.trackDoubleClicked.connect(self._on_result_activated)
        results_layout.addWidget(self._results_view, 1)
        splitter.addWidget(results_box)

        queue_box = QWidget()
        queue_layout = QVBoxLayout(queue_box)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        self._queue_label = QLabel(_("online.queue"))
        self._queue_label.setObjectName("networkSectionLabel")
        queue_layout.addWidget(self._queue_label)
        self._queue_view = PlaylistView(context_menu_enabled=False)
        self._queue_view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self._queue_view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._queue_view.trackDoubleClicked.connect(self.queuePlayRequested.emit)
        queue_layout.addWidget(self._queue_view, 1)
        splitter.addWidget(queue_box)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    def set_online_playlist(self, playlist: PlaylistManager):
        self._queue = playlist
        self._queue_view.setModel(playlist)
        playlist.modelReset.connect(self._update_queue_label)
        playlist.rowsInserted.connect(self._update_queue_label)
        playlist.rowsRemoved.connect(self._update_queue_label)
        self._update_queue_label()

    def _update_queue_label(self, *_args):
        self._queue_label.setText(f"{_('online.queue')}（{self._queue.count}）")
        self._queue_view.viewport().update()

    def refresh_highlight(self):
        self._results_view.viewport().update()
        self._queue_view.viewport().update()

    # ------------------------------------------------------------------
    #  Provider lifecycle
    # ------------------------------------------------------------------

    def set_provider(self, provider: OnlineProvider | None):
        if provider is None:
            self._provider = None
            self._provider_base = ""
            self._provider_healthy = False
            self._provider_label.setText(_("online.no_provider"))
            self._status.setText(_("online.no_provider"))
            self._set_enabled(False)
            return

        changed = provider.base_url != self._provider_base
        became_healthy = provider.healthy and not self._provider_healthy
        self._provider = provider
        self._provider_base = provider.base_url
        self._provider_healthy = provider.healthy

        if provider.healthy:
            self._provider_label.setText(provider.name)
            self._set_enabled(True)
            if provider.quality:
                self._on_quality_done(provider.quality, "")
            if changed or became_healthy:
                self._refresh_playlists()
                self._load_quality()
        else:
            self._provider_label.setText(f"{provider.name} · {_('online.offline')}")
            self._status.setText(_("online.offline"))
            self._set_enabled(False)

    def _set_enabled(self, enabled: bool):
        self._search_input.setEnabled(enabled)
        self._search_btn.setEnabled(enabled)
        self._quality_combo.setEnabled(enabled)
        self._playlist_combo.setEnabled(enabled)
        self._recommend_combo.setEnabled(enabled)
        self._refresh_batch_btn.setEnabled(enabled and bool(self._last_recommend))
        self._play_all_btn.setEnabled(enabled and bool(self._results_items))
        self._refresh_btn.setEnabled(self._provider is not None)

    def shutdown(self):
        container = getattr(self, "_results_model", None)
        if container is not None and hasattr(container, "shutdown"):
            container.shutdown()

    # ------------------------------------------------------------------
    #  Network workers
    # ------------------------------------------------------------------

    def _refresh_playlists(self, *_args):
        if self._provider is None:
            return
        provider = self._provider
        self._status.setText(_("online.loading"))
        self._refresh_btn.setEnabled(False)

        def worker():
            try:
                playlists = provider.playlists()
            except Exception as exc:
                self._playlistsDone.emit([], str(exc))
            else:
                self._playlistsDone.emit(playlists, "")

        threading.Thread(target=worker, daemon=True).start()

    def _load_quality(self):
        if self._provider is None:
            return
        provider = self._provider

        def worker():
            try:
                quality = provider.quality()
            except Exception as exc:
                self._qualityDone.emit("", str(exc))
            else:
                self._qualityDone.emit(quality, "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_quality_done(self, quality: str, error: str):
        if error or not quality:
            return
        index = self._quality_combo.findData(quality)
        if index >= 0:
            self._quality_combo.blockSignals(True)
            self._quality_combo.setCurrentIndex(index)
            self._quality_combo.blockSignals(False)

    def _on_quality_changed(self, _index: int):
        quality = self._quality_combo.currentData()
        if not quality or self._provider is None:
            return
        provider = self._provider
        label = self._quality_combo.currentText()
        self._status.setText(f"{_('online.quality_changed')}: {label}")

        def worker():
            try:
                provider.set_quality(quality)
            except Exception as exc:
                self._qualityDone.emit("", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_playlists_done(self, playlists: list, error: str):
        self._refresh_btn.setEnabled(True)
        self._playlist_combo.blockSignals(True)
        self._playlist_combo.clear()
        self._playlist_combo.addItem(_("online.select_playlist"), "")
        for item in playlists:
            count = item.get("count") or 0
            label = f"{item.get('title', '')}（{count}）" if count else item.get("title", "")
            self._playlist_combo.addItem(label, str(item.get("id", "")))
        self._playlist_combo.blockSignals(False)
        if error:
            self._status.setText(f"{_('online.load_failed')}: {error}")
        else:
            self._status.setText(f"{_('online.playlists_loaded')}: {len(playlists)}")

    def _reset_recommend(self):
        self._recommend_combo.blockSignals(True)
        self._recommend_combo.setCurrentIndex(0)
        self._recommend_combo.blockSignals(False)
        self._last_recommend = ""
        self._refresh_batch_btn.setEnabled(False)

    def _on_recommend_changed(self, _index: int):
        kind = self._recommend_combo.currentData()
        if not kind:
            return
        self._playlist_combo.blockSignals(True)
        self._playlist_combo.setCurrentIndex(0)
        self._playlist_combo.blockSignals(False)
        self._last_recommend = kind
        self._refresh_batch_btn.setEnabled(True)
        self._load_recommend(kind)

    def _refresh_batch(self):
        if not self._last_recommend:
            self._set_status_for_recommend(_("online.select_recommend"))
            return
        self._load_recommend(self._last_recommend)

    def _load_recommend(self, kind: str):
        if self._provider is None:
            return
        limits = {"daily": 30, "radio": 20, "radar": 30}
        provider = self._provider
        label = self._recommend_combo.currentText()
        self._status.setText(f"{_('online.loading')}: {label}")

        def worker():
            try:
                songs = provider.recommend(kind, limits.get(kind, 30))
            except Exception as exc:
                self._recommendDone.emit(kind, [], str(exc))
            else:
                self._recommendDone.emit(kind, songs, "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_recommend_done(self, kind: str, songs: list, error: str):
        self._on_results_done(songs, error)
        if not error and self._results_items:
            label = self._recommend_combo.currentText()
            self._status.setText(f"{label}: {len(self._results_items)}")

    def _set_status_for_recommend(self, text: str):
        self._status.setText(text)

    def _on_playlist_changed(self, _index: int):
        dissid = self._playlist_combo.currentData()
        if not dissid or self._provider is None:
            return
        self._reset_recommend()
        provider = self._provider
        name = self._playlist_combo.currentText()
        self._status.setText(f"{_('online.loading')}: {name}")

        def worker():
            try:
                songs = provider.playlist_songs(dissid, limit=500)
            except Exception as exc:
                self._resultsDone.emit([], str(exc))
            else:
                self._resultsDone.emit(songs, "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_search(self, *_args):
        keyword = self._search_input.text().strip()
        if not keyword or self._provider is None:
            return
        self._reset_recommend()
        self._search_id += 1
        search_id = self._search_id
        provider = self._provider
        self._status.setText(f"{_('online.searching')}: {keyword}")

        def worker():
            try:
                songs = provider.search(keyword, limit=50)
            except Exception as exc:
                self._searchDone.emit(search_id, [], str(exc))
            else:
                self._searchDone.emit(search_id, songs, "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_done(self, search_id: int, songs: list, error: str):
        if search_id != self._search_id:
            return
        self._on_results_done(songs, error)

    def _items_for(self, songs: list) -> list[tuple[str, dict]]:
        provider = self._provider
        if provider is None:
            return []
        items = []
        for song in songs:
            mid = str(song.get("mid") or "")
            if not mid:
                continue
            cover_url = (song.get("cover") or "").replace(
                "R300x300", "R150x150"
            )
            items.append((provider.stream_url(mid), {
                "title": song.get("title", ""),
                "artist": song.get("artist", ""),
                "album": song.get("album", ""),
                "duration_ms": int(song.get("duration") or 0),
                "cover_url": cover_url,
                "meta_url": provider.meta_url(mid),
            }))
        return items

    def _on_results_done(self, songs: list, error: str):
        if error:
            self._status.setText(f"{_('online.load_failed')}: {error}")
            return
        self._results_items = self._items_for(songs)
        self._results_model.set_urls(self._results_items)
        self._results_view.viewport().update()
        self._play_all_btn.setEnabled(bool(self._results_items))
        if not self._results_items:
            self._status.setText(_("online.empty"))
        else:
            self._status.setText(f"{_('online.results_loaded')}: {len(self._results_items)}")

    def _on_result_activated(self, index: int):
        if 0 <= index < len(self._results_items):
            self.playResultsRequested.emit(self._results_items, index)

    def _play_all(self):
        if self._results_items:
            self.playResultsRequested.emit(self._results_items, 0)
