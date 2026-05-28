from PyQt6.QtWidgets import QInputDialog, QMenu, QWidget
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QObject, pyqtSignal

from audio_player.app import current_accent
from audio_player.player.library import LibraryManager
from audio_player.player.playlist import PlaylistManager
from audio_player.i18n import _


class LibraryController(QObject):
    """Controller for library operations: favorites, playlists, and context menus."""

    playRequested = pyqtSignal(list)      # file paths to load into main playlist and play
    playlistChanged = pyqtSignal()         # when playlists/favorites data changes
    logMessage = pyqtSignal(str)           # for status bar messages
    navigateToPage = pyqtSignal(int)       # request content_stack page switch
    editTags = pyqtSignal(str)             # single file path for tag editing

    def __init__(self, library: LibraryManager, fav_playlist: PlaylistManager,
                 pls_playlist: PlaylistManager, parent=None):
        super().__init__(parent)
        self._library = library
        self._fav_playlist = fav_playlist
        self._pls_playlist = pls_playlist
        self._current_pls_name = ""

    # ---- Favorites page ----

    def refresh_favorites_page(self, fav_label):
        paths = self._library.get_favorites()
        self._fav_playlist.clear()
        if paths:
            self._fav_playlist.add_files(paths)
        fav_label.setText(_("page.favorites_count", count=len(paths)))

    def play_fav_track(self, idx: int):
        # Load favorites into main playlist and play
        path = self._fav_playlist.track_at(idx).get("path") if idx < self._fav_playlist.count else None
        if path:
            paths = self._library.get_favorites()
            self.playRequested.emit(paths)

    # ---- Playlists page ----

    def _refresh_playlists_page(self, pls_grid, make_card_fn):
        names = self._library.get_playlist_names()
        infos = []
        for name in names:
            paths = self._library.get_playlist_tracks(name)
            info = make_card_fn(name, paths, self._library)
            infos.append(info)
        pls_grid.set_playlists(infos)

    def _create_new_playlist(self):
        parent_w = self.parent() if isinstance(self.parent(), QWidget) else None
        name, ok = QInputDialog.getText(parent_w, _("playlist.new"), _("playlist.name_label") + ":")
        if ok and name.strip():
            if self._library.playlist_exists(name.strip()):
                self.logMessage.emit(_("log.playlist_exists", name=name.strip()))
            else:
                self._library.create_playlist(name.strip())
                self.playlistChanged.emit()
                self.logMessage.emit(_("log.playlist_created", name=name.strip()))

    def _open_playlist_detail(self, name: str, pls_detail_label):
        self._current_pls_name = name
        paths = self._library.get_playlist_tracks(name)
        pls_detail_label.setText(f"{name}  ({len(paths)})")
        self.navigateToPage.emit(6)

    def play_pls_track(self, idx: int):
        paths = self._library.get_playlist_tracks(self._current_pls_name)
        if paths and 0 <= idx < len(paths):
            self.playRequested.emit(paths)

    # ---- Favorites / playlist add/remove ----

    def on_add_to_favorites(self, paths: list[str]):
        self._library.add_to_favorites(paths)
        self.logMessage.emit(_("log.favorited", count=len(paths)))

    def on_remove_from_favorites(self, paths: list[str]):
        self._library.remove_from_favorites(paths)
        self.logMessage.emit(_("log.unfavorited", count=len(paths)))

    def on_add_to_playlist(self, name: str, paths: list[str]):
        if not name:
            # "新建歌单" was clicked
            parent_w = self.parent() if isinstance(self.parent(), QWidget) else None
            name, ok = QInputDialog.getText(parent_w, _("playlist.new"), _("playlist.name_label") + ":")
            if not ok or not name.strip():
                return
            name = name.strip()
            if not self._library.playlist_exists(name):
                self._library.create_playlist(name)
                self.playlistChanged.emit()
        self._library.add_to_playlist(name, paths)
        self.logMessage.emit(_("log.added_to_playlist", count=len(paths), name=name))

    def on_remove_from_pls(self, indices: list[int]):
        if self._current_pls_name:
            self._library.remove_from_playlist(self._current_pls_name, indices)
            self.playlistChanged.emit()
            self.logMessage.emit(_("log.removed_from_playlist", count=len(indices)))

    # ---- Context menu ----

    def show_more_menu(self, btn_widget, current_file):
        path = current_file
        if not path:
            self.logMessage.emit(_("log.no_playing"))
            return

        from audio_player.ui.theme_helpers import menu_style
        menu = QMenu(btn_widget)
        menu.setStyleSheet(menu_style())

        is_fav = self._library.is_favorite(path)
        fav_text = _("context.unfavorite") if is_fav else _("context.favorite")
        fav_action = QAction(fav_text, self)
        fav_action.triggered.connect(lambda: (
            self.on_remove_from_favorites([path]) if is_fav
            else self.on_add_to_favorites([path])
        ))
        menu.addAction(fav_action)

        names = self._library.get_playlist_names()
        if names:
            menu.addSeparator()
            pls_menu = menu.addMenu(_("context.add_to_playlist"))
            pls_menu.setStyleSheet(menu.styleSheet())
            for name in names:
                act = QAction(name, self)
                act.triggered.connect(lambda checked, n=name: self.on_add_to_playlist(n, [path]))
                pls_menu.addAction(act)
            pls_menu.addSeparator()
            new_act = QAction(_("context.new_playlist"), self)
            new_act.triggered.connect(lambda: self.on_add_to_playlist("", [path]))
            pls_menu.addAction(new_act)
        else:
            menu.addSeparator()
            new_act = QAction(_("context.add_to_playlist"), self)
            new_act.triggered.connect(lambda: self.on_add_to_playlist("", [path]))
            menu.addAction(new_act)

        # Edit tags
        menu.addSeparator()
        edit_tags_act = QAction(_("context.edit_tags"), self)
        edit_tags_act.triggered.connect(lambda: self.editTags.emit(path))
        menu.addAction(edit_tags_act)

        btn_pos = btn_widget.mapToGlobal(btn_widget.rect().topLeft())
        menu.exec(btn_pos)
