from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QGridLayout, QFrame, QDialog,
                             QPushButton, QListWidget, QListWidgetItem,
                             QSplitter, QSizePolicy, QListView, QStyledItemDelegate,
                             QStyle, QLayout)
from PyQt6.QtCore import (Qt, pyqtSignal, QSettings, QSize, QRect,
                         QModelIndex, QAbstractListModel, QTimer)
from PyQt6.QtGui import (QPainter, QColor, QFont, QPen, QPixmap, QFontMetrics,
                         QPainterPath)
from audio_player.app import current_accent, current_theme_mode
import os

from audio_player.player.album_manager import AlbumInfo
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.i18n import _


def _is_light_mode() -> bool:
    return current_theme_mode() == "light"


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
                cover.setText("💿")
                cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};font-size:48px;")
        else:
            cover.setText("💿")
            cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};font-size:48px;")
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
            text = child.text()
            if text and text != "💿":
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
            font = QFont(painter.font())
            font.setPointSize(16)
            painter.setFont(font)
            painter.setPen(QColor("#64748b"))
            painter.drawText(QRect(cover_x, cover_y, cover_size, cover_size),
                           Qt.AlignmentFlag.AlignCenter, "💿")

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
        self._albums: list[AlbumInfo] = []
        self._cards: list[AlbumCardWidget] = []
        self._view_mode = "grid"

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
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color:#64748b;font-size:14px;padding:40px;")
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
        self._albums = albums
        # Destroy old cards
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        # Create new cards (once)
        for album in self._albums:
            card = AlbumCardWidget(album)
            card.clicked.connect(self.albumClicked)
            self._cards.append(card)

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
# ---------------------------------------------------------------------------

def _format_dur(sec: float) -> str:
    if sec <= 0:
        return "--:--"
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# Flow layout — wraps child widgets when width is insufficient
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=-1):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._hspacing = spacing if spacing >= 0 else 6
        self._vspacing = 4
        if parent:
            self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for item in self._items:
            s = s.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        ml, mt, mr, _ = m.left(), m.top(), m.right(), m.bottom()
        x = ml
        y = mt
        line_h = 0
        max_w = rect.width() - mr

        for item in self._items:
            size = item.sizeHint()
            if x + size.width() > max_w and x > ml:
                x = ml
                y += line_h + self._vspacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(x, y, size.width(), size.height()))
            x += size.width() + self._hspacing
            line_h = max(line_h, size.height())

        return y + line_h + m.bottom() + self._vspacing


# ---------------------------------------------------------------------------
# Album track list model + delegate (PlaylistView-style)
# ---------------------------------------------------------------------------

class _AlbumTrackModel(QAbstractListModel):
    HeaderRole = Qt.ItemDataRole.UserRole + 1
    TrackNumRole = Qt.ItemDataRole.UserRole + 2
    TitleRole = Qt.ItemDataRole.UserRole + 3
    ArtistRole = Qt.ItemDataRole.UserRole + 4
    DurationRole = Qt.ItemDataRole.UserRole + 5
    FilePathRole = Qt.ItemDataRole.UserRole + 6
    IsCurrentRole = Qt.ItemDataRole.UserRole + 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._current_playlist_idx: int | None = None

    @property
    def current_index(self):
        """Return model row index of the currently playing track, or -1."""
        if self._current_playlist_idx is None:
            return -1
        for r, item in enumerate(self._items):
            if item.get("playlist_idx") == self._current_playlist_idx:
                return r
        return -1

    def set_current_playlist_idx(self, idx: int | None):
        old = self._current_playlist_idx
        self._current_playlist_idx = idx
        if old != idx:
            # Refresh rows for old and new current track
            for r, item in enumerate(self._items):
                if item.get("playlist_idx") in (old, idx):
                    self.dataChanged.emit(self.index(r, 0), self.index(r, 0))

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return item.get("playlist_idx")
        if role == self.HeaderRole:
            return item.get("type") == "header"
        if role == self.IsCurrentRole:
            return item.get("playlist_idx") == self._current_playlist_idx
        if role == self.TrackNumRole:
            return item.get("track_num", 0)
        if role == self.TitleRole:
            return item.get("title", "")
        if role == self.ArtistRole:
            return item.get("artist", "")
        if role == self.DurationRole:
            return item.get("duration_sec", 0)
        if role == self.FilePathRole:
            return item.get("filepath", "")
        if role == Qt.ItemDataRole.DisplayRole:
            return item.get("disc_label", "") if item.get("type") == "header" else item.get("title", "")
        return None

    def set_tracks(self, disc_groups: dict[int, list[tuple]]):
        self.beginResetModel()
        self._items = []
        for disc in sorted(disc_groups.keys()):
            if len(disc_groups) > 1:
                self._items.append({"type": "header", "disc_label": f"CD {disc}"})
            for idx, tn, title, artist, dur in sorted(disc_groups[disc], key=lambda x: x[1]):
                self._items.append({
                    "type": "track",
                    "playlist_idx": idx,
                    "track_num": tn,
                    "title": title,
                    "artist": artist,
                    "duration_sec": dur,
                })
        self.endResetModel()


class _AlbumTrackDelegate(QStyledItemDelegate):
    MARGIN = 2

    def paint(self, painter: QPainter, option, index: QModelIndex):
        model = index.model()
        is_header = model.data(index, _AlbumTrackModel.HeaderRole)

        if is_header:
            self._paint_header(painter, option, index)
        else:
            self._paint_track(painter, option, index)

    def _paint_header(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        rect = option.rect
        is_light = _is_light_mode()
        color = QColor("#999999") if is_light else QColor("#555555")
        painter.setPen(color)
        font = QFont(painter.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        label = index.data(Qt.ItemDataRole.DisplayRole)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"── {label} ──")
        painter.restore()

    def _paint_track(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        model = index.model()

        rect = option.rect.adjusted(self.MARGIN, 2, -self.MARGIN, -2)
        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_light = _is_light_mode()
        accent = current_accent()

        # Selection background
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            c = QColor(accent)
            c.setAlpha(40)
            painter.setBrush(c)
            painter.drawRoundedRect(rect, 6, 6)

        # Current playing indicator
        is_current = bool(model.data(index, _AlbumTrackModel.IsCurrentRole))
        if is_current:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(
                QRect(rect.x() + 4, rect.y() + 8, 3, rect.height() - 16), 1.5, 1.5)

        # Track number
        track_num = model.data(index, _AlbumTrackModel.TrackNumRole) or 0
        num_font = QFont(painter.font())
        num_font.setPointSize(9)
        painter.setFont(num_font)
        painter.setPen(accent if is_current else QColor("#64748b"))
        tn_str = f"{track_num:02d}" if track_num else "??"
        painter.drawText(QRect(rect.x() + 14, rect.y(), 28, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, tn_str)

        # Text area
        text_x = rect.x() + 44
        text_w = rect.width() - 44 - 8

        title = model.data(index, _AlbumTrackModel.TitleRole) or "Unknown"
        artist = model.data(index, _AlbumTrackModel.ArtistRole) or ""
        dur_sec = model.data(index, _AlbumTrackModel.DurationRole) or 0

        # Title
        title_font = QFont(painter.font())
        title_font.setPointSize(10)
        title_font.setBold(is_current)
        painter.setFont(title_font)
        title_color = QColor("#333333") if is_light else QColor("#e2e8f0")
        painter.setPen(accent.lighter(130) if is_current else title_color)
        title_text = painter.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 4, text_w, 20,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, title_text)

        # Artist + Duration (same line, matching main playlist)
        sub_font = QFont(painter.font())
        sub_font.setPointSize(9)
        painter.setFont(sub_font)
        painter.setPen(QColor("#888888") if is_light else QColor("#64748b"))
        sub_text = artist
        if dur_sec:
            m, s = divmod(int(dur_sec), 60)
            sub_text = f"{artist}  ·  {m}:{s:02d}" if artist else f"{m}:{s:02d}"
        sub_text = painter.fontMetrics().elidedText(
            sub_text, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 22, text_w, 20,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub_text)

        painter.restore()

    def sizeHint(self, option, index):
        model = index.model()
        if model and model.data(index, _AlbumTrackModel.HeaderRole):
            return QSize(200, 28)
        return QSize(200, 52)


TRACK_LIST_STYLE = """
QListView {
    background: transparent;
    border: none;
    outline: none;
    padding: 2px;
}
QListView::item {
    padding: 0px;
    border: none;
}
"""


# ---------------------------------------------------------------------------
# Album detail page (inline)
# ---------------------------------------------------------------------------

class AlbumDetailPage(QWidget):
    backRequested = pyqtSignal()
    trackDoubleClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._album: AlbumInfo | None = None
        self._is_light = _is_light_mode()
        self._setup_ui()

    def _setup_ui(self):
        is_light = self._is_light
        back_color = "#666666" if is_light else "#94a3b8"
        back_hover_bg = "#e0e0e0" if is_light else "#1a1a2e"
        back_hover_color = "#333333" if is_light else "#fff"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Back button
        header = QHBoxLayout()
        header.setContentsMargins(8, 8, 8, 4)
        back_btn = QPushButton(_("album.back"))
        self._back_btn = back_btn
        back_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{back_color};border:none;"
            f"font-size:12px;padding:6px 12px;border-radius:4px;}}"
            f"QPushButton:hover{{background:{back_hover_bg};color:{back_hover_color};}}"
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
        self._name_label.setStyleSheet(self._name_style())
        self._name_label.setWordWrap(True)
        info_wrap.addWidget(self._name_label)

        self._artist_label = QLabel()
        self._artist_label.setStyleSheet(self._artist_style())
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
        info_color = "#666666" if is_light else "#64748b"
        track_label = QLabel(_("album.track_list"))
        self._track_label = track_label
        track_label.setStyleSheet(f"color:{info_color};font-size:10px;font-weight:bold;letter-spacing:2px;")
        body_layout.addWidget(track_label)

        self._track_model = _AlbumTrackModel(self)
        self._track_view = QListView()
        self._track_view.setModel(self._track_model)
        self._track_view.setItemDelegate(_AlbumTrackDelegate())
        self._track_view.setStyleSheet(TRACK_LIST_STYLE)
        self._track_view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._track_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._track_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._track_view.setMouseTracking(True)
        self._track_view.setSpacing(0)
        self._track_view.doubleClicked.connect(self._on_track_double_click)
        # Size policy: take remaining space, minimum 200px height
        self._track_view.setMinimumHeight(200)
        body_layout.addWidget(self._track_view, 1)

        scroll.setWidget(body)
        layout.addWidget(scroll)

    def _name_style(self):
        c = "#333333" if self._is_light else "#e2e8f0"
        return f"font-size:20px;font-weight:bold;color:{c};"

    def _artist_style(self):
        c = current_accent().name()
        return f"font-size:14px;color:{c};"

    def _meta_chip_style(self):
        is_light = self._is_light
        bg = "#f0f0f0" if is_light else "#141418"
        c = "#555555" if is_light else "#94a3b8"
        return f"background:{bg};color:{c};font-size:10px;padding:3px 8px;border-radius:3px;"

    def show_album(self, album: AlbumInfo):
        self._album = album

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
                self._cover_label.setText("💿")
                self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};font-size:48px;")
        else:
            self._cover_label.setText("💿")
            self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};font-size:48px;")

        # Metadata chips — build from album + first track audio specs
        self._rebuild_chips()

        # Track list model
        disc_groups: dict[int, list[tuple]] = {}
        from audio_player.player.metadata import read_metadata
        for idx, fp in album.tracks:
            meta = read_metadata(fp)
            dn = meta.disc_number if meta and meta.disc_number else 1
            tn = meta.track_number if meta and meta.track_number else 0
            title = meta.title if meta and meta.title else os.path.basename(fp)
            artist = meta.artist if meta and meta.artist else ""
            dur = meta.duration_seconds if meta and meta.duration_seconds else 0
            if dn not in disc_groups:
                disc_groups[dn] = []
            disc_groups[dn].append((idx, tn, title, artist, dur))
        # Fill missing track numbers with sequential numbering per disc
        for disc, tracks in disc_groups.items():
            tracks.sort(key=lambda x: x[1] if x[1] else 9999)
            next_num = 1
            for i, (idx, tn, title, artist, dur) in enumerate(tracks):
                if not tn:
                    while any(t[1] == next_num for t in tracks):
                        next_num += 1
                    tracks[i] = (idx, next_num, title, artist, dur)
                    next_num += 1

        self._track_model.set_tracks(disc_groups)

    def _on_track_double_click(self, idx: QModelIndex):
        val = idx.data(Qt.ItemDataRole.UserRole)
        if val is not None:
            self.trackDoubleClicked.emit(int(val))

    def set_current_playlist_index(self, playlist_idx: int | None):
        self._track_model.set_current_playlist_idx(playlist_idx)

    def refresh_theme_mode(self, is_light: bool):
        self._is_light = is_light
        cover_bg = "#e0e0e0" if is_light else "#141414"

        cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
        radius_px = "12px" if cover_radius else "2px"
        self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        self._name_label.setStyleSheet(self._name_style())
        self._artist_label.setStyleSheet(self._artist_style())

        info_color = "#666666" if is_light else "#64748b"
        self._track_label.setStyleSheet(f"color:{info_color};font-size:10px;font-weight:bold;letter-spacing:2px;")

        chip_style = self._meta_chip_style()
        for i in range(self._meta_layout.count()):
            item = self._meta_layout.itemAt(i)
            if item and item.widget():
                item.widget().setStyleSheet(chip_style)

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

        chip_style = self._meta_chip_style()
        for text in chips:
            lbl = QLabel(text)
            lbl.setStyleSheet(chip_style)
            self._meta_layout.addWidget(lbl)


# ---------------------------------------------------------------------------
# Album detail dialog
# ---------------------------------------------------------------------------

class AlbumDetailDialog(QDialog):
    trackDoubleClicked = pyqtSignal(int)

    def __init__(self, album: AlbumInfo, parent=None):
        super().__init__(parent)
        self._album = album
        self.setWindowTitle(f"{album.name} — {album.artist}" if album.artist else album.name)
        self.setMinimumSize(640, 460)
        self.resize(680, 500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        is_light = _is_light_mode()
        cover_bg = "#e0e0e0" if is_light else "#141414"
        name_color = "#333333" if is_light else "#e2e8f0"
        artist_color = current_accent().name()

        main = QHBoxLayout(self)
        main.setContentsMargins(20, 20, 20, 20)
        main.setSpacing(20)

        left = QVBoxLayout()
        cover = QLabel()
        cover.setFixedSize(220, 220)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setStyleSheet(f"background:{cover_bg};border-radius:10px;")
        if album.cover_data:
            pix = QPixmap()
            ok = pix.loadFromData(album.cover_data)
            if ok and not pix.isNull():
                cover.setPixmap(pix.scaled(210, 210, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
            else:
                cover.setText("💿")
                cover.setStyleSheet(f"background:{cover_bg};border-radius:10px;font-size:60px;")
        else:
            cover.setText("💿")
            cover.setStyleSheet(f"background:{cover_bg};border-radius:10px;font-size:60px;")
        left.addWidget(cover)
        left.addStretch()
        main.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(6)

        name_lbl = QLabel(album.name or _("album.unknown_album"))
        name_lbl.setStyleSheet(f"font-size:18px;font-weight:bold;color:{name_color};")
        name_lbl.setWordWrap(True)
        right.addWidget(name_lbl)

        if album.artist:
            artist_lbl = QLabel(album.artist)
            artist_lbl.setStyleSheet(f"font-size:13px;color:{artist_color};")
            right.addWidget(artist_lbl)

        right.addSpacing(10)

        info_color = "#666666" if is_light else "#64748b"
        info_value_color = "#333333" if is_light else "#e2e8f0"

        info_grid = QGridLayout()
        info_grid.setSpacing(4)
        rows = []
        if album.year:
            rows.append((_("album.year") + ":", str(album.year)))
        rows.append((_("album.track_count") + ":", _("album.tracks_unit", count=album.track_count)))
        rows.append((_("album.total_duration") + ":", _format_dur(album.total_duration)))
        if album.formats:
            rows.append((_("album.format") + ":", album.formats))
        rows.append((_("album.total_size") + ":", _format_size(album.total_size)))
        if album.disc_count > 1:
            rows.append((_("album.disc_count") + ":", _("album.discs_unit", count=album.disc_count)))

        for r, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet(f"color:{info_color};font-size:11px;")
            vl = QLabel(v)
            vl.setStyleSheet(f"color:{info_value_color};font-size:11px;")
            info_grid.addWidget(kl, r, 0, Qt.AlignmentFlag.AlignRight)
            info_grid.addWidget(vl, r, 1, Qt.AlignmentFlag.AlignLeft)
        right.addLayout(info_grid)

        right.addSpacing(8)

        track_label = QLabel(_("album.track_list") + ":")
        track_label.setStyleSheet(f"color:{info_color};font-size:10px;font-weight:bold;letter-spacing:2px;")
        right.addWidget(track_label)

        accent = current_accent()
        accent_rgba = accent.darker(180).name()

        track_bg = "#fafafa" if is_light else "#080808"
        track_border = "#e0e0e0" if is_light else "#1a1a1a"
        track_color = "#333333" if is_light else "#d0d0d0"
        track_hover = "#f0f0f0" if is_light else "#141414"

        track_list = QListWidget()
        track_list.setStyleSheet(
            f"QListWidget{{background:{track_bg};border:1px solid {track_border};border-radius:4px;"
            f"color:{track_color};font-size:11px;}}"
            f"QListWidget::item{{padding:4px 8px;}}"
            f"QListWidget::item:hover{{background:{track_hover};}}"
            f"QListWidget::item:selected{{background:{accent_rgba};}}"
        )

        disc_groups: dict[int, list[tuple[int, str]]] = {}
        for idx, fp in album.tracks:
            from audio_player.player.metadata import read_metadata
            meta = read_metadata(fp)
            dn = meta.disc_number if meta and meta.disc_number else 1
            tn = meta.track_number if meta and meta.track_number else 0
            title = meta.title if meta and meta.title else os.path.basename(fp)
            dur = _format_dur(meta.duration_seconds) if meta and meta.duration_seconds else ""
            if dn not in disc_groups:
                disc_groups[dn] = []
            disc_groups[dn].append((idx, tn, title, dur))
        # Fill missing track numbers with sequential numbering per disc
        for disc, tracks in disc_groups.items():
            tracks.sort(key=lambda x: x[1] if x[1] else 9999)
            next_num = 1
            for i, (idx, tn, title, dur) in enumerate(tracks):
                if not tn:
                    while any(t[1] == next_num for t in tracks):
                        next_num += 1
                    tracks[i] = (idx, next_num, title, dur)
                    next_num += 1

        for disc in sorted(disc_groups.keys()):
            if len(disc_groups) > 1:
                header = QListWidgetItem(f"── CD {disc} ──")
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(QColor("#64748b"))
                font = QFont()
                font.setPointSize(10)
                font.setBold(True)
                header.setFont(font)
                track_list.addItem(header)

            for idx, tn, title, dur in sorted(disc_groups[disc], key=lambda x: x[1]):
                tn_str = f"{tn:02d}" if tn else "??"
                text = f"  {tn_str}.  {title}  {dur}" if dur else f"  {tn_str}.  {title}"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, idx)
                track_list.addItem(item)

        track_list.itemDoubleClicked.connect(
            lambda item: self._on_track_double_click(item))
        right.addWidget(track_list, 1)

        main.addLayout(right, 1)

    def _on_track_double_click(self, item: QListWidgetItem):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.trackDoubleClicked.emit(int(idx))
            self.accept()

    def refresh_theme_mode(self, is_light: bool):
        cover_bg = "#e0e0e0" if is_light else "#141414"
        name_color = "#333333" if is_light else "#e2e8f0"
        artist_color = current_accent().name()
        info_color = "#666666" if is_light else "#64748b"
        info_value_color = "#333333" if is_light else "#e2e8f0"
        track_bg = "#fafafa" if is_light else "#080808"
        track_border = "#e0e0e0" if is_light else "#1a1a1a"
        track_color = "#333333" if is_light else "#d0d0d0"
        track_hover = "#f0f0f0" if is_light else "#141414"
        accent = current_accent()
        accent_rgba = accent.darker(180).name()

        for child in self.findChildren(QLabel):
            if child.pixmap() and not child.pixmap().isNull():
                child.setStyleSheet(f"background:{cover_bg};border-radius:10px;")
                break

        for child in self.findChildren(QLabel):
            text = child.text()
            if not text:
                continue
            if child.styleSheet().find("font-size:18px") >= 0:
                child.setStyleSheet(f"font-size:18px;font-weight:bold;color:{name_color};")
            elif child.styleSheet().find("font-size:13px") >= 0:
                child.setStyleSheet(f"font-size:13px;color:{artist_color};")
            elif "font-size:10px" in child.styleSheet() and "letter-spacing:2px" in child.styleSheet():
                child.setStyleSheet(f"color:{info_color};font-size:10px;font-weight:bold;letter-spacing:2px;")

        for child in self.findChildren(QLabel):
            if child.styleSheet().find("font-size:11px") >= 0:
                if child.styleSheet().find("font-weight:bold") >= 0:
                    child.setStyleSheet(f"color:{info_value_color};font-size:11px;")
                else:
                    child.setStyleSheet(f"color:{info_color};font-size:11px;")

        for child in self.findChildren(QListWidget):
            child.setStyleSheet(
                f"QListWidget{{background:{track_bg};border:1px solid {track_border};border-radius:4px;"
                f"color:{track_color};font-size:11px;}}"
                f"QListWidget::item{{padding:4px 8px;}}"
                f"QListWidget::item:hover{{background:{track_hover};}}"
                f"QListWidget::item:selected{{background:{accent_rgba};}}"
            )
