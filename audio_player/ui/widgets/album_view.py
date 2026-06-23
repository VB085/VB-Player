from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QGridLayout, QFrame,
                             QPushButton,
                             QSplitter, QSizePolicy, QListView, QStyledItemDelegate,
                             QStyle, QLayout, QMenu)
from PyQt6.QtCore import (Qt, pyqtSignal, QSettings, QSize, QRect,
                         QModelIndex, QAbstractListModel, QTimer)
from typing import Callable
from PyQt6.QtGui import (QPainter, QColor, QFont, QPen, QPixmap, QFontMetrics,
                         QPainterPath, QAction)
from audio_player.app import current_accent, current_theme_mode
import os

from audio_player.player.album_manager import AlbumInfo
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.i18n import _
from audio_player.ui.icons import ALBUM_PLACEHOLDER, _icon
from audio_player.ui.shared import FlowLayout, set_placeholder_icon as _set_placeholder_icon
from audio_player.ui.utils import (
    format_duration as _format_dur, format_size as _format_size,
    is_light_mode as _is_light_mode,
)


# ---------------------------------------------------------------------------
# Album card (grid mode)
# ---------------------------------------------------------------------------

class AlbumCardWidget(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, album: AlbumInfo, parent=None):
        super().__init__(parent)
        self.setObjectName("albumCard")
        self.setFixedSize(172, 210)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._album = album

        is_light = _is_light_mode()
        cover_bg = "#e0e0e0" if is_light else "#141414"
        name_color = "#333333" if is_light else "#e2e8f0"
        artist_color = "#666666" if is_light else "#64748b"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Cover art
        cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
        radius_px = "12px" if cover_radius else "2px"
        cover = QLabel()
        cover.setFixedSize(152, 152)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        if album.cover_data:
            pix = QPixmap()
            ok = pix.loadFromData(album.cover_data)
            if ok and not pix.isNull():
                scaled_pix = pix.scaled(142, 142, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)
                if cover_radius:
                    rounded = QPixmap(142, 142)
                    rounded.fill(Qt.GlobalColor.transparent)
                    pt = QPainter(rounded)
                    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 142, 142, 12, 12)
                    pt.setClipPath(path)
                    pt.drawPixmap(0, 0, scaled_pix)
                    pt.end()
                    cover.setPixmap(rounded)
                else:
                    cover.setPixmap(scaled_pix)
            else:
                _set_placeholder_icon(cover)
                cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        else:
            _set_placeholder_icon(cover)
            cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        layout.addWidget(cover, 0, Qt.AlignmentFlag.AlignCenter)

        # Album name
        name_label = QLabel(album.name or _("album.unknown_album"))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(f"color:{name_color};font-size:12px;font-weight:bold;")
        name_label.setMaximumWidth(170)
        name_label.setWordWrap(False)
        fm = QFontMetrics(name_label.font())
        elided = fm.elidedText(album.name or _("album.unknown_album"), Qt.TextElideMode.ElideRight, 170)
        name_label.setText(elided)
        layout.addWidget(name_label)

        # Artist
        artist_label = QLabel(album.artist or "")
        artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        artist_label.setStyleSheet(f"color:{artist_color};font-size:10px;")
        artist_label.setMaximumWidth(170)
        fm2 = QFontMetrics(artist_label.font())
        elided2 = fm2.elidedText(album.artist or "", Qt.TextElideMode.ElideRight, 170)
        artist_label.setText(elided2)
        layout.addWidget(artist_label)

    def refresh_theme_mode(self, is_light: bool):
        cover_bg = "#e0e0e0" if is_light else "#141414"
        name_color = "#333333" if is_light else "#e2e8f0"
        artist_color = "#666666" if is_light else "#64748b"

        cover = self.findChild(QLabel)
        if cover:
            cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
            radius_px = "12px" if cover_radius else "2px"
            cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")

        for child in self.findChildren(QLabel):
            if child == cover:
                continue
            # Skip labels with pixmap (placeholder icons)
            if child.pixmap() and not child.pixmap().isNull():
                continue
            text = child.text()
            if text:
                if child.maximumWidth() == 170:
                    if child.styleSheet().find("font-weight:bold") >= 0:
                        child.setStyleSheet(f"color:{name_color};font-size:12px;font-weight:bold;")
                    else:
                        child.setStyleSheet(f"color:{artist_color};font-size:10px;")

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.clicked.emit(self._album)


# ---------------------------------------------------------------------------
# Album list model + delegate + view (list mode)
# ---------------------------------------------------------------------------

class AlbumListModel(QAbstractListModel):
    """Simple model that holds a list of AlbumInfo for the list view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._albums: list[AlbumInfo] = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._albums)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        album = self._albums[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return album
        return None

    def set_albums(self, albums: list[AlbumInfo]):
        self.beginResetModel()
        self._albums = list(albums)
        self.endResetModel()


class AlbumListDelegate(QStyledItemDelegate):
    MARGIN = 2

    def paint(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(self.MARGIN, 2, -self.MARGIN, -2)
        is_selected = option.state & QStyle.StateFlag.State_Selected
        accent = current_accent()
        is_light = _is_light_mode()

        # Background
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            c = QColor(accent)
            c.setAlpha(40)
            painter.setBrush(c)
            painter.drawRoundedRect(rect, 6, 6)

        # Cover thumbnail
        cover_x = rect.x() + 4
        cover_y = rect.y() + 4
        cover_size = 44
        cover_bg = QColor("#e0e0e0") if is_light else QColor("#1a1a2e")
        album = index.data(Qt.ItemDataRole.UserRole)
        cover_drawn = False
        if album and album.cover_data:
            pix = QPixmap()
            ok = pix.loadFromData(album.cover_data)
            if ok and not pix.isNull():
                scaled = pix.scaled(cover_size, cover_size, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                clip_path = QPainterPath()
                clip_path.addRoundedRect(cover_x, cover_y, cover_size, cover_size, 4, 4)
                painter.setClipPath(clip_path)
                painter.drawPixmap(cover_x, cover_y, scaled)
                painter.setClipping(False)
                cover_drawn = True

        if not cover_drawn:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(cover_bg)
            painter.drawRoundedRect(cover_x, cover_y, cover_size, cover_size, 4, 4)
            # Draw placeholder icon
            icon = _icon(ALBUM_PLACEHOLDER, color="#64748b")
            icon_size = 32
            icon_x = cover_x + (cover_size - icon_size) // 2
            icon_y = cover_y + (cover_size - icon_size) // 2
            icon.paint(painter, icon_x, icon_y, icon_size, icon_size)

        # Text area
        text_x = cover_x + cover_size + 12
        text_w = rect.width() - text_x - 60

        name = album.name if album else _("album.unknown_album")
        artist = album.artist if album else ""
        count = album.track_count if album else 0
        dur_str = _format_dur(album.total_duration) if album else ""

        # Album name
        name_font = QFont(painter.font())
        name_font.setPointSize(11)
        name_font.setBold(True)
        painter.setFont(name_font)
        name_color = QColor("#333333") if is_light else QColor("#e2e8f0")
        painter.setPen(name_color)
        name_text = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 6, text_w, 20,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, name_text)

        # Artist + info
        sub_font = QFont(painter.font())
        sub_font.setPointSize(9)
        painter.setFont(sub_font)
        sub_color = QColor("#888888") if is_light else QColor("#64748b")
        painter.setPen(sub_color)
        parts = []
        if artist:
            parts.append(artist)
        parts.append(_("album.tracks_unit", count=count))
        if dur_str and dur_str != "--:--":
            parts.append(dur_str)
        sub_text = "  ·  ".join(parts)
        sub_text = painter.fontMetrics().elidedText(sub_text, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 24, text_w, 20,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub_text)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(200, 56)


ALBUM_LIST_STYLE = """
QListView {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px;
}
QListView::item {
    padding: 0px;
    border: none;
}
"""


class AlbumListView(QListView):
    albumClicked = pyqtSignal(object)
    albumDoubleClicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("albumListView")
        self.setStyleSheet(ALBUM_LIST_STYLE)
        self._model = AlbumListModel(self)
        self.setModel(self._model)
        self.setItemDelegate(AlbumListDelegate())
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setSpacing(0)

        self.clicked.connect(self._on_click)
        self.doubleClicked.connect(self._on_double_click)

    def _on_click(self, idx: QModelIndex):
        album = idx.data(Qt.ItemDataRole.UserRole)
        if album:
            self.albumClicked.emit(album)

    def _on_double_click(self, idx: QModelIndex):
        album = idx.data(Qt.ItemDataRole.UserRole)
        if album:
            self.albumDoubleClicked.emit(album)

    def set_albums(self, albums: list[AlbumInfo]):
        self._model.set_albums(albums)

    def refresh_theme_mode(self, is_light: bool):
        self.viewport().update()


# ---------------------------------------------------------------------------
# Album grid container (wraps both grid and list views)
# ---------------------------------------------------------------------------

class AlbumGridView(QWidget):
    albumClicked = pyqtSignal(object)
    trackDoubleClicked = pyqtSignal(int)

    CARD_W = 172
    CARD_SPACING = 8

    def __init__(self, playlist_manager=None, parent=None):
        super().__init__(parent)
        self._playlist = playlist_manager
        self._all_albums: list[AlbumInfo] = []  # unfiltered source
        self._albums: list[AlbumInfo] = []       # currently displayed
        self._cards: list[AlbumCardWidget] = []
        self._view_mode = "grid"
        self._filter_text = ""

        # Debounce timer for resize
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(100)
        self._relayout_timer.timeout.connect(self._do_relayout)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Stacked widget: grid | list
        self._stack = AnimatedStackedWidget()

        # --- Page 0: Grid ---
        grid_page = QWidget()
        grid_layout = QVBoxLayout(grid_page)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setContentsMargins(12, 12, 12, 12)
        self._grid.setSpacing(self.CARD_SPACING)
        self._scroll.setWidget(self._grid_container)
        grid_layout.addWidget(self._scroll)
        self._stack.addWidget(grid_page)  # index 0

        # --- Page 1: List ---
        self._list_view = AlbumListView()
        self._list_view.albumClicked.connect(self.albumClicked)
        self._list_view.albumDoubleClicked.connect(self.albumClicked)
        self._stack.addWidget(self._list_view)  # index 1

        main_layout.addWidget(self._stack)

    # ------------------------------------------------------------------
    # View mode
    # ------------------------------------------------------------------

    def view_mode(self) -> str:
        return self._view_mode

    def set_view_mode(self, mode: str):
        if mode == self._view_mode:
            return
        self._view_mode = mode
        if mode == "list":
            self._list_view.set_albums(self._albums)
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)
            self._relayout_grid()

    # ------------------------------------------------------------------
    # Grid layout (card-caching, no-teardown on resize)
    # ------------------------------------------------------------------

    def _relayout_grid(self):
        """Schedule a debounced relayout."""
        self._relayout_timer.start()

    def _do_relayout(self):
        """Actually re-layout the grid. Cards are cached and reused."""
        # Remove all widgets from grid without destroying them
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().hide()

        if not self._albums:
            empty = QLabel(_("album.no_albums"))
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(empty, 0, 0)
            # Hide cached cards
            for card in self._cards:
                card.hide()
            return

        avail_w = self._scroll.viewport().width() if self._scroll.viewport() else self.width()
        cols = max(1, (avail_w + self.CARD_SPACING) // (self.CARD_W + self.CARD_SPACING))
        total_w = cols * self.CARD_W + (cols - 1) * self.CARD_SPACING
        margin = max(8, (avail_w - total_w) // 2)

        self._grid.setContentsMargins(margin, 12, margin, 12)
        self._grid.setSpacing(self.CARD_SPACING)

        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // cols, i % cols, Qt.AlignmentFlag.AlignLeft)
            card.show()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_albums(self, albums: list[AlbumInfo]):
        self._all_albums = albums
        self._apply_filter()

    def set_filter(self, text: str):
        """Filter displayed albums by *text* (matches name or artist)."""
        self._filter_text = text.lower()
        self._apply_filter()

    def _apply_filter(self):
        if self._filter_text:
            p = self._filter_text
            self._albums = [a for a in self._all_albums
                            if p in (a.name or "").lower() or p in (a.artist or "").lower()]
        else:
            self._albums = list(self._all_albums)

        # Reuse cards by key — second visit is instant
        old = {(c._album.name or "", c._album.artist or ""): c for c in self._cards}
        kept = set()
        new = []
        for album in self._albums:
            key = (album.name or "", album.artist or "")
            card = old.get(key) or AlbumCardWidget(album)
            if key in old:
                kept.add(id(card))
            else:
                card.clicked.connect(self.albumClicked)
            new.append(card)
        for card in self._cards:
            if id(card) not in kept:
                card.setParent(None); card.deleteLater()
        self._cards = new

        if self._view_mode == "grid":
            self._relayout_grid()
        else:
            self._list_view.set_albums(self._albums)

    def refresh_from_playlist(self):
        if self._playlist is None:
            return
        from audio_player.player.album_manager import AlbumManager
        mgr = AlbumManager()
        albums = mgr.group_by_album(self._playlist._tracks)
        self.set_albums(albums)

    def refresh_theme_mode(self, is_light: bool):
        # Update grid cards
        for card in self._cards:
            card.refresh_theme_mode(is_light)
        # Update list
        self._list_view.refresh_theme_mode(is_light)

    def refresh_language(self):
        """Recreate cards and update list with current language."""
        if self._albums:
            self.set_albums(self._albums)
        self._list_view.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view_mode == "grid" and self._albums:
            self._relayout_grid()


# ---------------------------------------------------------------------------
# Helpers
# _AlbumTrackModel, _AlbumTrackDelegate, TRACK_LIST_STYLE —
# imported from audio_player.ui.shared (see top of file)


# ---------------------------------------------------------------------------
# Album detail page (inline)
# ---------------------------------------------------------------------------

class AlbumDetailPage(QWidget):
    backRequested = pyqtSignal()
    trackDoubleClicked = pyqtSignal(int)
    addToFavorites = pyqtSignal(list)
    removeFromFavorites = pyqtSignal(list)
    addToPlaylist = pyqtSignal(str, list)
    editTags = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._album: AlbumInfo | None = None
        self._is_light = _is_light_mode()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Back button — circular icon, top-left
        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        back_btn = QPushButton("←")
        self._back_btn = back_btn
        back_btn.setFixedSize(32, 32)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setToolTip(_("album.back"))
        back_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.06);color:#94a3b8;border:none;"
            "border-radius:16px;font-size:16px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.12);color:#e2e8f0;}"
        )
        back_btn.clicked.connect(self.backRequested)
        header.addWidget(back_btn)
        header.addStretch()
        layout.addLayout(header)

        # Body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 8, 20, 20)
        body_layout.setSpacing(14)

        # --- Top: cover + info ---
        top = QHBoxLayout()
        top.setSpacing(24)

        # Cover
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(180, 180)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self._cover_label)

        # Info
        info_wrap = QVBoxLayout()
        info_wrap.setSpacing(4)

        self._name_label = QLabel()
        self._name_label.setObjectName("detailName")
        self._name_label.setWordWrap(True)
        info_wrap.addWidget(self._name_label)

        self._artist_label = QLabel()
        self._artist_label.setObjectName("detailArtist")
        info_wrap.addWidget(self._artist_label)

        info_wrap.addSpacing(8)

        # Metadata chips — flow layout wraps to next row when narrow
        self._meta_widget = QWidget()
        self._meta_layout = FlowLayout(self._meta_widget, spacing=6)
        self._meta_layout.setContentsMargins(0, 0, 0, 0)
        info_wrap.addWidget(self._meta_widget)

        info_wrap.addStretch()
        top.addLayout(info_wrap, 1)
        body_layout.addLayout(top)

        # --- Track list ---
        track_label = QLabel(_("album.track_list"))
        track_label.setObjectName("sectionLabel")
        self._track_label = track_label
        body_layout.addWidget(track_label)

        from audio_player.ui.widgets.playlist_view import PlaylistView
        from audio_player.player.playlist import PlaylistManager

        self._track_model = PlaylistManager(self)
        self._track_view = PlaylistView()
        self._track_view.setModel(self._track_model)
        self._track_view.setMinimumHeight(200)
        self._track_view.trackDoubleClicked.connect(self._on_track_double_click)

        self._is_favorite_fn: Callable[[str], bool] | None = None
        self._get_playlist_names_fn: Callable[[], list[str]] | None = None
        # Forward context menu actions from PlaylistView to this page
        self._track_view.addToFavorites.connect(lambda paths: self.addToFavorites.emit(paths))
        self._track_view.removeFromFavorites.connect(lambda paths: self.removeFromFavorites.emit(paths))
        self._track_view.addToPlaylist.connect(lambda name, paths: self.addToPlaylist.emit(name, paths))
        body_layout.addWidget(self._track_view, 1)

        scroll.setWidget(body)
        layout.addWidget(scroll)

    def show_album(self, album: AlbumInfo):
        self._album = album
        # Forward callbacks to the PlaylistView for context menu
        self._track_view._is_favorite_fn = self._is_favorite_fn
        self._track_view._get_playlist_names_fn = self._get_playlist_names_fn

        self._name_label.setText(album.name or _("album.unknown_album"))
        self._artist_label.setText(album.artist or _("album.unknown_artist"))
        self._artist_label.setVisible(True)

        # Cover
        is_light = self._is_light
        cover_bg = "#e0e0e0" if is_light else "#141414"
        cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
        radius_px = "12px" if cover_radius else "2px"
        self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        if album.cover_data:
            pix = QPixmap()
            ok = pix.loadFromData(album.cover_data)
            if ok and not pix.isNull():
                scaled = pix.scaled(170, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                if cover_radius:
                    rounded = QPixmap(170, 170)
                    rounded.fill(Qt.GlobalColor.transparent)
                    pt = QPainter(rounded)
                    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 170, 170, 12, 12)
                    pt.setClipPath(path)
                    pt.drawPixmap(0, 0, scaled)
                    pt.end()
                    self._cover_label.setPixmap(rounded)
                else:
                    self._cover_label.setPixmap(scaled)
            else:
                _set_placeholder_icon(self._cover_label)
                self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        else:
            _set_placeholder_icon(self._cover_label)
            self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")

        # Metadata chips — build from album + first track audio specs
        self._rebuild_chips()

        # Load tracks into PlaylistManager
        self._track_model.clear()
        paths = [fp for _, fp in album.tracks]
        if paths:
            self._track_model.add_files(paths)

    def _on_track_double_click(self, idx: int):
        self.trackDoubleClicked.emit(idx)

    def _show_context_menu(self, pos):
        idx = self._track_view.indexAt(pos)
        if not idx.isValid():
            return
        filepath = idx.data(self._track_model.FilePathRole)
        if not filepath:
            return

        from audio_player.ui.theme_helpers import menu_style
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())

        # Favorites toggle
        is_fav = self._is_favorite_fn and self._is_favorite_fn(filepath)
        fav_text = _("context.unfavorite") if is_fav else _("context.favorite")
        fav_action = QAction(fav_text, self)
        fav_action.triggered.connect(lambda: (
            self.removeFromFavorites.emit([filepath]) if is_fav
            else self.addToFavorites.emit([filepath])
        ))
        menu.addAction(fav_action)

        # Add to playlist submenu
        if self._get_playlist_names_fn:
            names = self._get_playlist_names_fn()
            if names:
                menu.addSeparator()
                pls_menu = menu.addMenu(_("context.add_to_playlist"))
                pls_menu.setStyleSheet(menu.styleSheet())
                for name in names:
                    act = QAction(name, self)
                    act.triggered.connect(lambda checked, n=name: self.addToPlaylist.emit(n, [filepath]))
                    pls_menu.addAction(act)
                pls_menu.addSeparator()
                new_act = QAction(_("context.new_playlist"), self)
                new_act.triggered.connect(lambda: self.addToPlaylist.emit("", [filepath]))
                pls_menu.addAction(new_act)

        # Edit tags
        menu.addSeparator()
        edit_tags_act = QAction(_("context.edit_tags"), self)
        edit_tags_act.triggered.connect(lambda: self.editTags.emit(filepath))
        menu.addAction(edit_tags_act)

        menu.exec(self._track_view.viewport().mapToGlobal(pos))

    def set_current_playlist_index(self, playlist_idx: int | None):
        if playlist_idx is not None:
            self._track_model.current_index = playlist_idx

    def refresh_accent(self):
        accent = current_accent()
        self._back_btn.setStyleSheet(
            f"QPushButton{{background:rgba(255,255,255,0.06);color:{accent.lighter(130).name()};border:none;"
            f"border-radius:16px;font-size:16px;}}"
            "QPushButton:hover{background:rgba(255,255,255,0.12);color:#e2e8f0;}"
        )
        self.update()

    def refresh_theme_mode(self, is_light: bool):
        self._is_light = is_light
        cover_bg = "#e0e0e0" if is_light else "#141414"

        cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
        radius_px = "12px" if cover_radius else "2px"
        self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        self._track_view.viewport().update()

    def refresh_language(self):
        """Update all translatable text and rebuild chips."""
        if hasattr(self, '_back_btn'):
            self._back_btn.setText(_("album.back"))
        if hasattr(self, '_track_label'):
            self._track_label.setText(_("album.track_list"))
        if self._album is not None:
            self._name_label.setText(self._album.name or _("album.unknown_album"))
            self._artist_label.setText(self._album.artist or _("album.unknown_artist"))
            # Rebuild chips
            self._rebuild_chips()
        self._track_view.viewport().update()

    def _rebuild_chips(self):
        """Rebuild metadata chips with current language."""
        album = self._album
        if album is None:
            return
        while self._meta_layout.count():
            item = self._meta_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sample_rate = 0
        bitrate = 0
        bits_per_sample = 0
        channels = 0
        from audio_player.player.metadata import read_metadata
        if album.tracks:
            first_meta = read_metadata(album.tracks[0][1])
            if first_meta:
                sample_rate = first_meta.sample_rate
                bitrate = first_meta.bitrate
                bits_per_sample = first_meta.bits_per_sample
                channels = first_meta.channels

        chips = []
        if album.year:
            chips.append(str(album.year))
        chips.append(_("album.tracks_unit", count=album.track_count))
        chips.append(_format_dur(album.total_duration))
        if album.formats:
            chips.append(album.formats.upper())
        if bitrate:
            chips.append(f"{bitrate // 1000}kbps" if bitrate >= 1000 else f"{bitrate}bps")
        if sample_rate:
            chips.append(f"{sample_rate / 1000:.1f}kHz" if sample_rate >= 1000 else f"{sample_rate}Hz")
        if bits_per_sample:
            chips.append(f"{bits_per_sample}bit")
        if channels == 2:
            chips.append(_("misc.stereo"))
        elif channels == 1:
            chips.append(_("misc.mono"))
        elif channels > 2:
            chips.append(_("misc.channels", n=channels))
        chips.append(_format_size(album.total_size))
        if album.disc_count > 1:
            chips.append(f"{album.disc_count} CD")

        for text in chips:
            lbl = QLabel(text)
            lbl.setObjectName("metaChip")
            self._meta_layout.addWidget(lbl)
