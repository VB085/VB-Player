"""Playlist browse widgets — grid/list view, detail page, edit dialog."""

from typing import Callable
from dataclasses import dataclass, field
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QGridLayout,
    QFrame, QDialog, QPushButton, QLineEdit, QTextEdit, QFileDialog,
    QListView, QStyledItemDelegate, QStyle, QMenu, QMessageBox,
    QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings, QSize, QRect, QModelIndex, QAbstractListModel, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QPixmap, QFontMetrics, QPainterPath, QAction
from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _
from audio_player.player.metadata import read_metadata
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.ui.widgets.playlist_view import PlaylistView
from audio_player.player.playlist import PlaylistManager
from audio_player.ui.shared import FlowLayout, set_placeholder_icon as _set_placeholder_icon
from audio_player.ui.icons import ALBUM_PLACEHOLDER, _icon
from audio_player.ui.utils import (
    format_duration as _format_dur, format_size as _format_size,
    is_light_mode as _is_light_mode,
)
import os


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class PlaylistInfo:
    name: str
    description: str = ""
    track_count: int = 0
    total_duration: float = 0.0
    total_size: int = 0
    cover_data: bytes | None = None
    formats: str = ""
    tracks: list[str] = field(default_factory=list)  # file paths


def build_playlist_info(name: str, paths: list[str], library=None) -> PlaylistInfo:
    """Build PlaylistInfo from playlist name and track paths.

    Reads metadata for stats and cover art. If *library* is provided,
    uses its custom description/cover_path overrides.
    """
    info = PlaylistInfo(name=name, tracks=list(paths))
    formats_seen: set[str] = set()
    cover_data = None

    for fp in paths:
        meta = read_metadata(fp)
        if meta:
            if meta.cover_data and not cover_data:
                cover_data = meta.cover_data
            info.total_duration += meta.duration_seconds or 0
            info.total_size += meta.file_size or 0
            if meta.format:
                formats_seen.add(meta.format)

    info.track_count = len(paths)
    info.formats = " / ".join(sorted(formats_seen)) if formats_seen else ""
    info.cover_data = cover_data

    # Apply library overrides (description, custom cover)
    if library:
        meta_dict = library.get_playlist_meta(name)
        info.description = meta_dict.get("description", "")
        cover_path = meta_dict.get("cover_path", "")
        if cover_path and os.path.isfile(cover_path):
            try:
                with open(cover_path, "rb") as f:
                    info.cover_data = f.read()
            except OSError:
                pass

    return info


# ---------------------------------------------------------------------------
# Card widget (grid mode)
# ---------------------------------------------------------------------------

class PlaylistCardWidget(QFrame):
    clicked = pyqtSignal(object)
    editRequested = pyqtSignal(object)
    deleteRequested = pyqtSignal(object)

    def __init__(self, info: PlaylistInfo, parent=None):
        super().__init__(parent)
        self.setObjectName("playlistCard")
        self.setFixedSize(172, 210)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._info = info

        is_light = _is_light_mode()
        cover_bg = "#e0e0e0" if is_light else "#141414"
        name_color = "#333333" if is_light else "#e2e8f0"
        sub_color = "#666666" if is_light else "#64748b"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Cover
        cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
        radius_px = "12px" if cover_radius else "2px"
        cover = QLabel()
        cover.setFixedSize(152, 152)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        if info.cover_data:
            pix = QPixmap()
            ok = pix.loadFromData(info.cover_data)
            if ok and not pix.isNull():
                scaled = pix.scaled(142, 142, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                if cover_radius:
                    rounded = QPixmap(142, 142)
                    rounded.fill(Qt.GlobalColor.transparent)
                    pt = QPainter(rounded)
                    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, 142, 142, 12, 12)
                    pt.setClipPath(path)
                    pt.drawPixmap(0, 0, scaled)
                    pt.end()
                    cover.setPixmap(rounded)
                else:
                    cover.setPixmap(scaled)
            else:
                _set_placeholder_icon(cover)
                cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        else:
            _set_placeholder_icon(cover)
            cover.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        layout.addWidget(cover, 0, Qt.AlignmentFlag.AlignCenter)

        # Name
        name_label = QLabel(info.name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(f"color:{name_color};font-size:12px;font-weight:bold;")
        name_label.setMaximumWidth(170)
        fm = QFontMetrics(name_label.font())
        name_label.setText(fm.elidedText(info.name, Qt.TextElideMode.ElideRight, 170))
        layout.addWidget(name_label)

        # Subtitle: track count
        sub_label = QLabel(_("playlist.tracks_unit", count=info.track_count))
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setStyleSheet(f"color:{sub_color};font-size:10px;")
        layout.addWidget(sub_label)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._info)

    def contextMenuEvent(self, event):
        from audio_player.ui.theme_helpers import menu_style
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())
        edit_act = QAction(_("playlist.edit"), self)
        edit_act.triggered.connect(lambda: self.editRequested.emit(self._info))
        menu.addAction(edit_act)

        delete_act = QAction(_("playlist.delete"), self)
        delete_act.triggered.connect(lambda: self.deleteRequested.emit(self._info))
        menu.addAction(delete_act)

        menu.exec(event.globalPos())

    def refresh_theme_mode(self, is_light: bool):
        # Recreate is simpler for cards; parent handles it
        pass


# ---------------------------------------------------------------------------
# List model + delegate (list mode)
# ---------------------------------------------------------------------------

class PlaylistListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[PlaylistInfo] = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        if role == Qt.ItemDataRole.UserRole:
            return self._items[index.row()]
        return None

    def set_playlists(self, items: list[PlaylistInfo]):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()


class PlaylistListDelegate(QStyledItemDelegate):
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

        info = index.data(Qt.ItemDataRole.UserRole)
        if not info:
            painter.restore()
            return

        # Cover thumbnail
        cover_x = rect.x() + 4
        cover_y = rect.y() + 4
        cover_size = 44
        cover_bg = QColor("#e0e0e0") if is_light else QColor("#1a1a2e")
        cover_drawn = False
        if info.cover_data:
            pix = QPixmap()
            ok = pix.loadFromData(info.cover_data)
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
            # Draw placeholder icon
            icon = _icon(ALBUM_PLACEHOLDER, color="#64748b")
            icon_size = 32
            icon_x = cover_x + (cover_size - icon_size) // 2
            icon_y = cover_y + (cover_size - icon_size) // 2
            icon.paint(painter, icon_x, icon_y, icon_size, icon_size)

        # Text area
        text_x = cover_x + cover_size + 12
        text_w = rect.width() - text_x - 60

        name = info.name
        count = info.track_count
        dur_str = _format_dur(info.total_duration) if info.total_duration else ""

        # Name
        name_font = QFont(painter.font())
        name_font.setPointSize(11)
        name_font.setBold(True)
        painter.setFont(name_font)
        name_color = QColor("#333333") if is_light else QColor("#e2e8f0")
        painter.setPen(name_color)
        fm = QFontMetrics(name_font)
        name_text = fm.elidedText(name, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 6, text_w, 20,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, name_text)

        # Subtitle
        sub_font = QFont(painter.font())
        sub_font.setPointSize(9)
        painter.setFont(sub_font)
        sub_color = QColor("#888888") if is_light else QColor("#64748b")
        painter.setPen(sub_color)
        parts = [_("playlist.tracks_unit", count=count)]
        if dur_str and dur_str != "--:--":
            parts.append(dur_str)
        sub_text = "  ·  ".join(parts)
        sub_text = fm.elidedText(sub_text, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 24, text_w, 20,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub_text)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(200, 56)


PLAYLIST_LIST_STYLE = """
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


class PlaylistListView(QListView):
    playlistClicked = pyqtSignal(object)
    playlistDoubleClicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(PLAYLIST_LIST_STYLE)
        self._model = PlaylistListModel(self)
        self._delegate = PlaylistListDelegate()
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.clicked.connect(self._on_click)
        self.doubleClicked.connect(self._on_double_click)

    def set_playlists(self, items: list[PlaylistInfo]):
        self._model.set_playlists(items)

    def _on_click(self, idx: QModelIndex):
        info = idx.data(Qt.ItemDataRole.UserRole)
        if info:
            self.playlistClicked.emit(info)

    def _on_double_click(self, idx: QModelIndex):
        info = idx.data(Qt.ItemDataRole.UserRole)
        if info:
            self.playlistDoubleClicked.emit(info)

    def refresh_theme_mode(self, is_light: bool):
        self.viewport().update()


# ---------------------------------------------------------------------------
# Grid view container (grid + list toggle)
# ---------------------------------------------------------------------------

class PlaylistGridView(QWidget):
    playlistClicked = pyqtSignal(object)
    editRequested = pyqtSignal(object)
    deleteRequested = pyqtSignal(object)

    CARD_W = 172
    CARD_SPACING = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playlists: list[PlaylistInfo] = []
        self._cards: list[PlaylistCardWidget] = []
        self._view_mode = "grid"

        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(100)
        self._relayout_timer.timeout.connect(self._do_relayout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = AnimatedStackedWidget()

        # Grid page
        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(12, 8, 12, 8)
        self._grid_layout.setSpacing(self.CARD_SPACING)
        self._grid_scroll.setWidget(self._grid_container)

        # No-playlists label
        self._empty_label = QLabel(_("playlist.no_playlists"))
        self._empty_label.setObjectName("emptyState")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)

        # List page
        self._list_view = PlaylistListView()
        self._list_view.playlistClicked.connect(self.playlistClicked)

        self._stack.addWidget(self._grid_scroll)   # index 0
        self._stack.addWidget(self._list_view)      # index 1
        layout.addWidget(self._stack)

    def view_mode(self) -> str:
        return self._view_mode

    def set_view_mode(self, mode: str):
        if mode == self._view_mode:
            return
        self._view_mode = mode
        if mode == "list":
            self._list_view.set_playlists(self._playlists)
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)
            self._relayout_grid()

    def filter(self, text: str):
        """Show/hide cards matching filter text."""
        t = text.strip().lower()
        for card in self._cards:
            name = card._info.name.lower() if hasattr(card, '_info') else ""
            card.setVisible(t in name if t else True)

    def set_playlists(self, items: list[PlaylistInfo]):
        self._playlists = items
        # Destroy old cards
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()

        for info in items:
            card = PlaylistCardWidget(info)
            card.clicked.connect(self.playlistClicked)
            card.editRequested.connect(self.editRequested)
            card.deleteRequested.connect(self.deleteRequested)
            self._cards.append(card)

        if self._view_mode == "grid":
            self._relayout_grid()
        else:
            self._list_view.set_playlists(items)

    def _relayout_grid(self):
        self._relayout_timer.start()

    def _do_relayout(self):
        # Clear grid
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(self._grid_container)
                w.hide()

        if not self._cards:
            self._empty_label.setVisible(True)
            self._empty_label.setParent(self._grid_container)
            self._grid_layout.addWidget(self._empty_label, 0, 0)
            return

        self._empty_label.setVisible(False)
        avail_w = self._grid_scroll.viewport().width()
        spacing = self.CARD_SPACING
        cols = max(1, (avail_w + spacing) // (self.CARD_W + spacing))
        total_w = cols * self.CARD_W + (cols - 1) * spacing
        left_margin = max(8, (avail_w - total_w) // 2)
        self._grid_layout.setContentsMargins(left_margin, 8, left_margin, 8)

        for i, card in enumerate(self._cards):
            row = i // cols
            col = i % cols
            self._grid_layout.addWidget(card, row, col)
            card.show()

    def refresh_theme_mode(self, is_light: bool):
        for c in self._cards:
            c.refresh_theme_mode(is_light)
        self._list_view.refresh_theme_mode(is_light)

    def refresh_language(self):
        self._empty_label.setText(_("playlist.no_playlists"))
        # Recreate cards to update translatable text
        items = self._playlists
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()
        for info in items:
            card = PlaylistCardWidget(info)
            card.clicked.connect(self.playlistClicked)
            card.editRequested.connect(self.editRequested)
            card.deleteRequested.connect(self.deleteRequested)
            self._cards.append(card)
        if self._view_mode == "grid":
            self._relayout_grid()
        self._list_view.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view_mode == "grid" and self._playlists:
            self._relayout_grid()


# ---------------------------------------------------------------------------
# Detail page (inline)
# ---------------------------------------------------------------------------

class PlaylistDetailPage(QWidget):
    backRequested = pyqtSignal()
    trackDoubleClicked = pyqtSignal(int)
    addToFavorites = pyqtSignal(list)
    removeFromFavorites = pyqtSignal(list)
    addToPlaylist = pyqtSignal(str, list)
    removeFromPlaylist = pyqtSignal(list)
    editRequested = pyqtSignal(object)
    editTags = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._info: PlaylistInfo | None = None
        self._is_light = _is_light_mode()
        self._is_favorite_fn: Callable[[str], bool] | None = None
        self._get_playlist_names_fn: Callable[[], list[str]] | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header: circular back ← · title · edit
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

        edit_btn = QPushButton(_("playlist.edit"))
        self._edit_btn = edit_btn
        edit_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#94a3b8;border:1px solid rgba(255,255,255,0.10);"
            "font-size:12px;padding:5px 14px;border-radius:6px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.06);color:#e2e8f0;}"
        )
        edit_btn.clicked.connect(self._on_edit)
        header.addWidget(edit_btn)
        layout.addLayout(header)

        # Body scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 8, 20, 20)
        body_layout.setSpacing(14)

        # Top: cover + info
        top = QHBoxLayout()
        top.setSpacing(24)

        self._cover_label = QLabel()
        self._cover_label.setFixedSize(180, 180)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self._cover_label)

        info_wrap = QVBoxLayout()
        info_wrap.setSpacing(4)

        self._name_label = QLabel()
        self._name_label.setObjectName("detailName")
        self._name_label.setWordWrap(True)
        info_wrap.addWidget(self._name_label)

        self._desc_label = QLabel()
        self._desc_label.setObjectName("detailDesc")
        self._desc_label.setWordWrap(True)
        info_wrap.addWidget(self._desc_label)

        info_wrap.addSpacing(8)

        # Metadata chips
        self._meta_widget = QWidget()
        self._meta_layout = FlowLayout(self._meta_widget, spacing=6)
        self._meta_layout.setContentsMargins(0, 0, 0, 0)
        info_wrap.addWidget(self._meta_widget)

        info_wrap.addStretch()
        top.addLayout(info_wrap, 1)
        body_layout.addLayout(top)

        # Track list — uses shared PlaylistView for cover thumbs, glow, drag reorder
        self._track_label = QLabel(_("album.track_list"))
        self._track_label.setObjectName("sectionLabel")
        body_layout.addWidget(self._track_label)

        self._track_model = PlaylistManager(self)
        self._track_view = PlaylistView()
        self._track_view.setModel(self._track_model)
        self._track_view.setMinimumHeight(200)
        self._track_view.trackDoubleClicked.connect(self._on_track_double_click)
        # Forward context menu actions
        self._track_view.addToFavorites.connect(lambda paths: self.addToFavorites.emit(paths))
        self._track_view.removeFromFavorites.connect(lambda paths: self.removeFromFavorites.emit(paths))
        self._track_view.addToPlaylist.connect(lambda name, paths: self.addToPlaylist.emit(name, paths))
        body_layout.addWidget(self._track_view, 1)

        scroll.setWidget(body)
        layout.addWidget(scroll)

    def show_playlist(self, info: PlaylistInfo):
        self._info = info
        self._track_view._is_favorite_fn = self._is_favorite_fn
        self._track_view._get_playlist_names_fn = self._get_playlist_names_fn

        self._name_label.setText(info.name)
        if info.description:
            self._desc_label.setText(info.description)
            self._desc_label.setVisible(True)
        else:
            self._desc_label.setVisible(False)

        # Cover
        is_light = self._is_light
        cover_bg = "#e0e0e0" if is_light else "#141414"
        cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
        radius_px = "12px" if cover_radius else "2px"
        self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        if info.cover_data:
            pix = QPixmap()
            ok = pix.loadFromData(info.cover_data)
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

        # Chips
        self._rebuild_chips()

        # Track list — load into PlaylistManager
        self._track_model.clear()
        paths = list(info.tracks) if info.tracks else []
        if paths:
            self._track_model.add_files(paths)

    def _on_track_double_click(self, idx: int):
        self.trackDoubleClicked.emit(idx)

    def _on_edit(self):
        if self._info:
            self.editRequested.emit(self._info)

    def _show_context_menu(self, pos):
        idx = self._track_view.indexAt(pos)
        if not idx.isValid():
            return
        filepath = idx.data(PlaylistManager.FilePathRole)
        if not filepath:
            return

        from audio_player.ui.theme_helpers import menu_style
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())

        # Favorites
        is_fav = self._is_favorite_fn and self._is_favorite_fn(filepath)
        fav_text = _("context.unfavorite") if is_fav else _("context.favorite")
        fav_action = QAction(fav_text, self)
        fav_action.triggered.connect(lambda: (
            self.removeFromFavorites.emit([filepath]) if is_fav
            else self.addToFavorites.emit([filepath])
        ))
        menu.addAction(fav_action)

        # Add to playlist
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

        # Remove from playlist
        if self._info:
            menu.addSeparator()
            rm_act = QAction(_("context.remove"), self)
            row = idx.row()
            rm_act.triggered.connect(lambda: self.removeFromPlaylist.emit([int(row)]))
            menu.addAction(rm_act)

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
        """Update inline accent-styled elements."""
        accent = current_accent()
        self._back_btn.setStyleSheet(
            f"QPushButton{{background:rgba(255,255,255,0.06);color:{accent.lighter(130).name()};border:none;"
            f"border-radius:16px;font-size:16px;}}"
            "QPushButton:hover{background:rgba(255,255,255,0.12);color:#e2e8f0;}"
        )
        self._track_view.update()
        self._track_view.repaint()
        self.update()

    def _rebuild_chips(self):
        """Rebuild metadata chips (track count, duration, size, format)."""
        # Clear existing chips
        while self._meta_layout.count():
            item = self._meta_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._info or not self._info.tracks:
            return
        from audio_player.ui.utils import format_duration as _fd, format_size as _fs
        total_secs = 0
        total_size = 0
        formats = set()
        for fp in self._info.tracks:
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
                ext = os.path.splitext(fp)[1].lower().lstrip('.')
                if ext:
                    formats.add(ext.upper())
        # Estimate duration from track metadata if available
        if self._track_model.rowCount() > 0:
            for i in range(self._track_model.rowCount()):
                dur = self._track_model.index(i, 0).data(self._track_model.DurationRole)
                if dur:
                    total_secs += dur
        # Chips
        count_chip = QLabel(_("album.track_count") + f": {len(self._info.tracks)}")
        count_chip.setObjectName("metaChip")
        self._meta_layout.addWidget(count_chip)
        if total_secs > 0:
            dur_chip = QLabel(_("album.total_duration") + f": {_fd(int(total_secs))}")
            dur_chip.setObjectName("metaChip")
            self._meta_layout.addWidget(dur_chip)
        if total_size > 0:
            size_chip = QLabel(_("album.total_size") + f": {_fs(total_size)}")
            size_chip.setObjectName("metaChip")
            self._meta_layout.addWidget(size_chip)
        if formats:
            fmt_chip = QLabel(_("album.format") + f": {', '.join(sorted(formats))}")
            fmt_chip.setObjectName("metaChip")
            self._meta_layout.addWidget(fmt_chip)

    def refresh_theme_mode(self, is_light: bool):
        self._is_light = is_light
        cover_bg = "#e0e0e0" if is_light else "#141414"
        cover_radius = str(QSettings("VBPlayer", "VB Player").value("album_cover_radius", "true")).lower() == "true"
        radius_px = "12px" if cover_radius else "2px"
        self._cover_label.setStyleSheet(f"background:{cover_bg};border-radius:{radius_px};")
        self._track_view.viewport().update()

    def refresh_language(self):
        self._back_btn.setText(_("album.back"))
        self._edit_btn.setText(_("playlist.edit"))
        self._track_label.setText(_("album.track_list"))
        if self._info:
            self._name_label.setText(self._info.name)
            self._rebuild_chips()
        self._track_view.viewport().update()


# ---------------------------------------------------------------------------
# Edit dialog
# ---------------------------------------------------------------------------

class PlaylistEditDialog(QDialog):
    def __init__(self, info: PlaylistInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self._cover_path = ""
        self._cover_data = info.cover_data
        self.setWindowTitle(_("playlist.edit_title"))
        self.setMinimumWidth(400)
        from audio_player.platform import platform_info
        if platform_info.policy.titlebar_style == "frameless":
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        is_light = _is_light_mode()
        bg = "#ffffff" if is_light else "#0f0f0f"
        border = "#e0e0e0" if is_light else "#222222"
        text_c = "#333333" if is_light else "#e2e8f0"
        sub_c = "#666666" if is_light else "#94a3b8"
        input_bg = "#f8f8f8" if is_light else "#141418"
        accent = current_accent()

        self.setStyleSheet(
            f"QDialog{{background:{bg};border:1px solid {border};border-radius:12px;}}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Title
        title = QLabel(_("playlist.edit_title"))
        title.setStyleSheet(f"color:{text_c};font-size:16px;font-weight:bold;")
        layout.addWidget(title)

        # Name
        name_lbl = QLabel(_("playlist.name_label"))
        name_lbl.setStyleSheet(f"color:{sub_c};font-size:11px;")
        layout.addWidget(name_lbl)
        self._name_edit = QLineEdit(info.name)
        self._name_edit.setStyleSheet(
            f"QLineEdit{{background:{input_bg};color:{text_c};border:1px solid {border};"
            f"border-radius:6px;padding:8px 10px;font-size:13px;}}"
            f"QLineEdit:focus{{border:1px solid {accent.name()};}}"
        )
        layout.addWidget(self._name_edit)

        # Description
        desc_lbl = QLabel(_("playlist.desc_label"))
        desc_lbl.setStyleSheet(f"color:{sub_c};font-size:11px;")
        layout.addWidget(desc_lbl)
        self._desc_edit = QTextEdit()
        self._desc_edit.setPlainText(info.description)
        self._desc_edit.setMaximumHeight(80)
        self._desc_edit.setStyleSheet(
            f"QTextEdit{{background:{input_bg};color:{text_c};border:1px solid {border};"
            f"border-radius:6px;padding:8px 10px;font-size:12px;}}"
            f"QTextEdit:focus{{border:1px solid {accent.name()};}}"
        )
        layout.addWidget(self._desc_edit)

        # Cover
        cover_row = QHBoxLayout()
        cover_lbl = QLabel(_("playlist.cover_label"))
        cover_lbl.setStyleSheet(f"color:{sub_c};font-size:11px;")
        cover_row.addWidget(cover_lbl)
        cover_row.addStretch()

        self._cover_preview = QLabel()
        self._cover_preview.setFixedSize(64, 64)
        self._cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_cover_preview()
        self._cover_preview.mousePressEvent = self._pick_cover
        cover_row.addWidget(self._cover_preview)

        if info.cover_data:
            rm_btn = QPushButton(_("playlist.cover_remove"))
            rm_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{sub_c};border:none;font-size:11px;}}"
                f"QPushButton:hover{{color:{text_c};}}"
            )
            rm_btn.clicked.connect(self._remove_cover)
            self._rm_cover_btn = rm_btn
            cover_row.addWidget(rm_btn)
        else:
            self._rm_cover_btn = None

        layout.addLayout(cover_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton(_("settings.cancel"))
        cancel_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{sub_c};border:1px solid {border};"
            f"border-radius:6px;padding:8px 20px;font-size:12px;}}"
            f"QPushButton:hover{{color:{text_c};border-color:{text_c};}}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton(_("settings.ok"))
        ok_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
            f"border-radius:6px;padding:8px 20px;font-size:12px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def _update_cover_preview(self):
        if self._cover_data:
            pix = QPixmap()
            if pix.loadFromData(self._cover_data) and not pix.isNull():
                scaled = pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                rounded = QPixmap(64, 64)
                rounded.fill(Qt.GlobalColor.transparent)
                pt = QPainter(rounded)
                pt.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(0, 0, 64, 64, 6, 6)
                pt.setClipPath(path)
                pt.drawPixmap(0, 0, scaled)
                pt.end()
                self._cover_preview.setPixmap(rounded)
                return
        is_light = _is_light_mode()
        bg = "#e0e0e0" if is_light else "#1a1a2e"
        self._cover_preview.setStyleSheet(f"background:{bg};border-radius:6px;")
        _set_placeholder_icon(self._cover_preview, 32)

    def _pick_cover(self, event=None):
        path, _ = QFileDialog.getOpenFileName(
            self, _("playlist.cover_change"), "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp);;All Files (*)"
        )
        if path:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                pix = QPixmap()
                if pix.loadFromData(data) and not pix.isNull():
                    self._cover_data = data
                    self._cover_path = path
                    self._update_cover_preview()
            except OSError:
                pass

    def _remove_cover(self):
        self._cover_data = None
        self._cover_path = "__remove__"
        self._update_cover_preview()
        if self._rm_cover_btn:
            self._rm_cover_btn.setVisible(False)

    def get_name(self) -> str:
        return self._name_edit.text().strip()

    def get_description(self) -> str:
        return self._desc_edit.toPlainText().strip()

    def get_cover_path(self) -> str:
        return self._cover_path
