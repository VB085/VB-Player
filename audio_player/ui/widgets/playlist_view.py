from typing import Callable
from PyQt6.QtWidgets import (QListView, QStyledItemDelegate, QStyle,
                             QAbstractItemView, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect, QRectF, QModelIndex, QSortFilterProxyModel, QSettings, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QAction, QPixmap, QPainterPath
from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _

# Per-delegate thumbnail cache: filepath → (cover_data_hash, QPixmap)
_cover_cache: dict[str, tuple[int, QPixmap]] = {}
_current_file: str = ""  # globally tracked for playing indicator

THUMB_SIZE = 40
THUMB_RADIUS = 6


def _source_model(model):
    """Return the source model if *model* is a QSortFilterProxyModel, else *model*."""
    if isinstance(model, QSortFilterProxyModel):
        return model.sourceModel()
    return model


def _source_row(model, proxy_index):
    """Map a proxy index to source row. Returns proxy_index.row() if no proxy."""
    if isinstance(model, QSortFilterProxyModel):
        return model.mapToSource(proxy_index).row()
    return proxy_index.row()


def _thumbnail(src, index: QModelIndex, filepath: str) -> QPixmap | None:
    """Return cached 28×28 rounded cover thumbnail, or generate and cache."""
    cover_data = index.data(src.CoverDataRole) if src else None
    if not cover_data:
        return None
    # Use filepath as cache key; bust if cover_data changes
    h = hash(cover_data)
    if filepath in _cover_cache:
        old_h, pix = _cover_cache[filepath]
        if old_h == h:
            return pix
    pix = QPixmap()
    pix.loadFromData(cover_data)
    if pix.isNull():
        return None
    scaled = pix.scaled(THUMB_SIZE, THUMB_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    # Make rounded
    rounded = QPixmap(THUMB_SIZE, THUMB_SIZE)
    rounded.fill(Qt.GlobalColor.transparent)
    pp = QPainter(rounded)
    pp.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, THUMB_SIZE, THUMB_SIZE, THUMB_RADIUS, THUMB_RADIUS)
    pp.setClipPath(path)
    pp.drawPixmap((THUMB_SIZE - scaled.width()) // 2,
                  (THUMB_SIZE - scaled.height()) // 2, scaled)
    pp.end()
    _cover_cache[filepath] = (h, rounded)
    # Limit cache size
    if len(_cover_cache) > 500:
        for k in list(_cover_cache.keys())[:50]:
            del _cover_cache[k]
    return rounded


class _PlaylistDelegate(QStyledItemDelegate):
    MARGIN = 2
    ROW_H = 58

    def paint(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(self.MARGIN, 2, -self.MARGIN, -2)
        is_selected = option.state & QStyle.StateFlag.State_Selected
        proxy = index.model()
        row = index.row()
        accent = current_accent()
        is_light = current_theme_mode() == "light"
        src = _source_model(proxy)
        src_row = _source_row(proxy, index)

        # Background
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            c = QColor(accent)
            c.setAlpha(40)
            painter.setBrush(c)
            painter.drawRoundedRect(rect, 8, 8)

        # Cover thumbnail
        filepath = (index.data(src.FilePathRole) if src else "") or ""

        # Playing indicator — file path matching across all playlist instances
        is_current = bool(filepath and filepath == _current_file)
        highlight = str(QSettings("VBPlayer", "VB Player").value("current_track_highlight", "glow") or "glow")
        thumb = _thumbnail(src, index, filepath) if src else None
        cover_x = rect.x() + 14
        cover_y = rect.y() + (rect.height() - THUMB_SIZE) // 2

        # Glow highlight — backlight bloom behind current track cover
        if is_current and highlight == "glow":
            glow_margin = 4
            glow_rect = QRectF(cover_x - glow_margin, cover_y - glow_margin,
                               THUMB_SIZE + 2 * glow_margin, THUMB_SIZE + 2 * glow_margin)
            # Outer glow (large, very faint)
            glow_c = QColor(accent)
            glow_c.setAlpha(35)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow_c)
            gpath = QPainterPath()
            gpath.addRoundedRect(glow_rect.adjusted(-2, -2, 2, 2), THUMB_RADIUS + 2, THUMB_RADIUS + 2)
            painter.drawPath(gpath)
            # Inner glow ring
            glow_c.setAlpha(80)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(glow_c, 2)
            painter.setPen(pen)
            gpath2 = QPainterPath()
            gpath2.addRoundedRect(glow_rect, THUMB_RADIUS + 1, THUMB_RADIUS + 1)
            painter.drawPath(gpath2)
        elif is_current and highlight == "bar":
            # Classic accent bar
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRect(rect.x() + 4, rect.y() + 8, 4, rect.height() - 16), 2, 2)

        # Cover pixmap
        if thumb and not thumb.isNull():
            painter.drawPixmap(cover_x, cover_y, thumb)
        else:
            placeholder = QColor("#2a2a2a") if not is_light else QColor("#e0e0e0")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(placeholder)
            ppath = QPainterPath()
            ppath.addRoundedRect(cover_x, cover_y, THUMB_SIZE, THUMB_SIZE, THUMB_RADIUS, THUMB_RADIUS)
            painter.drawPath(ppath)

        # Text layout
        text_x = cover_x + THUMB_SIZE + 12
        text_w = rect.width() - (text_x - rect.x()) - 30

        title = (index.data(src.TitleRole) if src else "") or "Unknown"
        artist = (index.data(src.ArtistRole) if src else "") or ""
        dur_sec = (index.data(src.DurationRole) if src else 0) or 0

        # Title — 12pt
        title_font = QFont(painter.font())
        title_font.setPointSize(12)
        title_font.setBold(is_current)
        painter.setFont(title_font)
        title_c = QColor("#1a1a1a") if is_light else QColor("#e2e8f0")
        painter.setPen(title_c if not is_current else accent)
        title_text = painter.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 6, text_w, 22,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, title_text)

        # Artist + Duration — 10pt
        sub_font = QFont(painter.font())
        sub_font.setPointSize(10)
        painter.setFont(sub_font)
        painter.setPen(QColor("#888") if is_light else QColor("#94a3b8"))
        sub_text = artist
        if dur_sec:
            m, s = divmod(int(dur_sec), 60)
            sub_text = f"{artist}  ·  {m}:{s:02d}" if artist else f"{m}:{s:02d}"
        sub_text = painter.fontMetrics().elidedText(
            sub_text, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 28, text_w, 22,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub_text)

        # Missing file indicator
        import os
        if filepath and not os.path.exists(filepath):
            painter.setPen(QColor("#ef4444"))
            painter.drawText(rect.adjusted(0, 0, -8, 0),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             "✕")

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(200, self.ROW_H)


STYLE = """
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


class PlaylistView(QListView):
    trackClicked = pyqtSignal(int)
    trackDoubleClicked = pyqtSignal(int)
    tracksDropped = pyqtSignal(list)
    addToFavorites = pyqtSignal(list)       # file paths
    removeFromFavorites = pyqtSignal(list)  # file paths
    addToPlaylist = pyqtSignal(str, list)   # (playlist_name, file paths)
    playNext = pyqtSignal(list)            # insert paths after current
    editTags = pyqtSignal(str)             # single file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("playlistView")
        self.setStyleSheet(STYLE)
        self.setItemDelegate(_PlaylistDelegate())
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.clicked.connect(self._on_click)
        self.doubleClicked.connect(self._on_double_click)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # External callbacks for context menu state queries
        self._is_favorite_fn: Callable[[str], bool] | None = None
        self._get_playlist_names_fn: Callable[[], list[str]] | None = None

    def setFilterText(self, text: str):
        """Filter visible rows by *text* against title/artist/album."""
        from PyQt6.QtCore import QRegularExpression
        proxy = self.model()
        if isinstance(proxy, QSortFilterProxyModel):
            proxy.setFilterRegularExpression(QRegularExpression(text, QRegularExpression.PatternOption.CaseInsensitiveOption))

    def _on_click(self, idx: QModelIndex):
        self.trackClicked.emit(_source_row(self.model(), idx))

    def _on_double_click(self, idx: QModelIndex):
        self.trackDoubleClicked.emit(_source_row(self.model(), idx))

    def mousePressEvent(self, event):
        idx = self.indexAt(event.pos())
        if not idx.isValid():
            self.clearSelection()
        super().mousePressEvent(event)

    def _show_context_menu(self, pos):
        proxy = self.model()
        model = _source_model(proxy)
        if not model or not hasattr(model, 'FilePathRole'):
            return
        indices = self.selectedIndexes()
        if not indices:
            return

        paths = []
        for idx in indices:
            p = idx.data(model.FilePathRole)
            if p:
                paths.append(p)
        if not paths:
            return

        from audio_player.ui.theme_helpers import menu_style
        menu = QMenu(self)
        menu.setStyleSheet(menu_style())

        # Favorites toggle
        all_fav = self._is_favorite_fn and all(self._is_favorite_fn(p) for p in paths)
        fav_text = _("context.unfavorite") if all_fav else _("context.favorite")
        fav_action = QAction(fav_text, self)
        fav_action.triggered.connect(lambda: (
            self.removeFromFavorites.emit(paths) if all_fav
            else self.addToFavorites.emit(paths)
        ))
        menu.addAction(fav_action)

        # Play next
        menu.addSeparator()
        play_next_act = QAction(_("context.play_next"), self)
        play_next_act.triggered.connect(lambda: self.playNext.emit(paths))
        menu.addAction(play_next_act)

        # Add to playlist submenu
        if self._get_playlist_names_fn:
            names = self._get_playlist_names_fn()
            if names:
                menu.addSeparator()
                pls_menu = menu.addMenu(_("context.add_to_playlist"))
                pls_menu.setStyleSheet(menu.styleSheet())
                for name in names:
                    act = QAction(name, self)
                    act.triggered.connect(lambda checked, n=name: self.addToPlaylist.emit(n, paths))
                    pls_menu.addAction(act)
                pls_menu.addSeparator()
                new_act = QAction(_("context.new_playlist"), self)
                new_act.triggered.connect(lambda: self.addToPlaylist.emit("", paths))
                pls_menu.addAction(new_act)

        # Edit tags (single file only)
        if len(paths) == 1:
            menu.addSeparator()
            edit_tags_act = QAction(_("context.edit_tags"), self)
            edit_tags_act.triggered.connect(lambda: self.editTags.emit(paths[0]))
            menu.addAction(edit_tags_act)

        menu.exec(self.viewport().mapToGlobal(pos))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            from pathlib import Path
            all_paths = []
            for url in event.mimeData().urls():
                p = Path(url.toLocalFile())
                if p.is_dir():
                    all_paths.extend(
                        str(f) for f in p.rglob("*")
                        if f.suffix.lower() in {
                            ".mp3", ".flac", ".wav", ".ogg", ".opus",
                            ".m4a", ".aac", ".wma", ".aiff", ".ape", ".wv",
                            ".dsf", ".dff"
                        }
                    )
                else:
                    all_paths.append(str(p))
            if all_paths:
                self.tracksDropped.emit(sorted(all_paths))
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
