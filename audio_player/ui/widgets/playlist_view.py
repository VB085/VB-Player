from typing import Callable
from PyQt6.QtWidgets import (QListView, QStyledItemDelegate, QStyle,
                             QAbstractItemView, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect, QModelIndex, QSortFilterProxyModel
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QAction
from audio_player.app import current_accent
from audio_player.i18n import _


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


class _PlaylistDelegate(QStyledItemDelegate):
    MARGIN = 2

    def paint(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(self.MARGIN, 2, -self.MARGIN, -2)
        is_selected = option.state & QStyle.StateFlag.State_Selected
        proxy = index.model()
        row = index.row()
        accent = current_accent()
        src = _source_model(proxy)
        src_row = _source_row(proxy, index)

        # Background
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            c = QColor(accent)
            c.setAlpha(40)
            painter.setBrush(c)
            painter.drawRoundedRect(rect, 6, 6)

        # Playing indicator
        is_current = src and hasattr(src, 'current_index') and src.current_index == src_row
        if is_current:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRect(rect.x() + 4, rect.y() + 8, 3, rect.height() - 16), 1.5, 1.5)

        # Track number
        num_font = QFont(painter.font())
        num_font.setPointSize(9)
        painter.setFont(num_font)
        painter.setPen(QColor("#64748b") if not is_current else accent)
        painter.drawText(QRect(rect.x() + 9, rect.y(), 30, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(row + 1))

        # Text
        text_x = rect.x() + 50
        text_w = rect.width() - 50 - 50

        title = (index.data(src.TitleRole) if src else "") or "Unknown"
        artist = (index.data(src.ArtistRole) if src else "") or ""
        dur_sec = (index.data(src.DurationRole) if src else 0) or 0

        # Title
        title_font = QFont(painter.font())
        title_font.setPointSize(10)
        title_font.setBold(is_current)
        painter.setFont(title_font)
        painter.setPen(QColor("#e2e8f0") if not is_current else accent.lighter(130))
        title_text = painter.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 4, text_w, 20,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, title_text)

        # Artist + Duration
        sub_font = QFont(painter.font())
        sub_font.setPointSize(9)
        painter.setFont(sub_font)
        painter.setPen(QColor("#64748b"))
        sub_text = artist
        if dur_sec:
            m, s = divmod(int(dur_sec), 60)
            sub_text = f"{artist}  ·  {m}:{s:02d}" if artist else f"{m}:{s:02d}"
        sub_text = painter.fontMetrics().elidedText(
            sub_text, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 22, text_w, 20,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub_text)

        # Missing file indicator
        import os
        filepath = (index.data(src.FilePathRole) if src else "") or ""
        if filepath and not os.path.exists(filepath):
            painter.setPen(QColor("#ef4444"))
            painter.drawText(rect.adjusted(0, 0, -8, 0),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             "✕")

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(200, 52)


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
