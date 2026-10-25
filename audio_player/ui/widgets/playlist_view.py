import os
from typing import Callable
from PyQt6.QtWidgets import (QListView, QStyledItemDelegate, QStyle,
                             QAbstractItemView, QMenu)
from PyQt6.QtCore import (Qt, pyqtSignal, QSize, QRect, QRectF, QModelIndex,
                          QSortFilterProxyModel, QSettings, QTimer, QPoint)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QAction, QPixmap, QPainterPath
from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _

# Per-delegate thumbnail cache: filepath → QPixmap
_cover_cache: dict[str, QPixmap] = {}
_COVER_CACHE_MAX = 3000  # 40×40 ARGB ≈ 6.5 KB each — 3000 ≈ 20 MB, fine
_current_file: str = ""  # globally tracked for playing indicator
_highlight_mode: str = "glow"  # cached QSettings value — avoid I/O in paint()

# File-existence cache: os.path.exists() is a filesystem syscall — doing it
# per row per paint frame (a scrolling screenful = hundreds of stats per
# second) was a major scroll-jank source. Existence is session-stable for
# playback purposes; the ✕ indicator refreshes on next metadata reload.
_exists_cache: dict[str, bool] = {}
_EXISTS_CACHE_MAX = 8000


def _file_exists(filepath: str) -> bool:
    try:
        hit = _exists_cache.get(filepath)
    except TypeError:  # unhashable — shouldn't happen for paths
        return os.path.exists(filepath)
    if hit is None:
        if len(_exists_cache) > _EXISTS_CACHE_MAX:
            for k in list(_exists_cache.keys())[:1000]:
                del _exists_cache[k]
        hit = _exists_cache[filepath] = os.path.exists(filepath)
    return hit

THUMB_SIZE = 40
THUMB_RADIUS = 6


def refresh_highlight_cache():
    """Re-read current_track_highlight from QSettings — call on settings change."""
    global _highlight_mode
    try:
        _highlight_mode = str(QSettings("VBPlayer", "VB Player").value(
            "current_track_highlight", "glow") or "glow")
    except Exception:
        _highlight_mode = "glow"


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
    """Return cached 40×40 rounded cover thumbnail, or generate and cache."""
    cover_data = index.data(src.CoverDataRole) if src else None
    if not cover_data:
        return None
    # Fast path: filepath is unique — cover data doesn't change for same file
    if filepath in _cover_cache:
        return _cover_cache[filepath]
    pix = QPixmap()
    pix.loadFromData(cover_data)
    if pix.isNull():
        return None
    scaled = pix.scaled(THUMB_SIZE, THUMB_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
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
    _cover_cache[filepath] = rounded
    if len(_cover_cache) > _COVER_CACHE_MAX:
        for k in list(_cover_cache.keys())[:500]:
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
        highlight = _highlight_mode
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

        # Missing file indicator (existence cached — see _file_exists)
        if filepath and not _file_exists(filepath):
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
        self.setUniformItemSizes(True)  # fixed row height — lets QListView cache item geometry
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Cover thumbnail prewarm: generate thumbnails during idle time so
        # paint() is always a cache hit. Without this, fast-scrolling into a
        # fresh region decoded a screenful of covers synchronously in paint().
        self._prewarm_pos = 0
        self._prewarm_dc_model = None
        self._prewarm_timer = QTimer(self)
        self._prewarm_timer.setSingleShot(True)
        self._prewarm_timer.setInterval(0)
        self._prewarm_timer.timeout.connect(self._prewarm_step)

        self.clicked.connect(self._on_click)
        self.doubleClicked.connect(self._on_double_click)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # External callbacks for context menu state queries
        self._is_favorite_fn: Callable[[str], bool] | None = None
        self._get_playlist_names_fn: Callable[[], list[str]] | None = None

        # Visible-region metadata priority: when scrolling stops, the rows on
        # screen jump to the front of the loader queue so covers appear in
        # ~0.5 s instead of waiting behind the whole playlist's bulk load.
        self._prio_timer = QTimer(self)
        self._prio_timer.setSingleShot(True)
        self._prio_timer.setInterval(150)
        self._prio_timer.timeout.connect(self._prioritize_visible)
        self.verticalScrollBar().valueChanged.connect(self._prio_timer.start)

    def setModel(self, model):
        super().setModel(model)
        self._restart_prewarm(model)
        self._prio_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._prio_timer.start()

    def _prioritize_visible(self):
        model = self.model()
        if model is None:
            return
        src = _source_model(model)
        if not hasattr(src, "prioritize_rows"):
            return
        vh = self.viewport().height()
        top = self.indexAt(QPoint(10, 0))
        if not top.isValid():
            return
        bottom = self.indexAt(QPoint(10, max(0, vh - 1)))
        end = bottom.row() if bottom.isValid() else model.rowCount() - 1
        rows = []
        for pr in range(top.row(), min(end + 1, model.rowCount())):
            idx = model.index(pr, 0)
            if idx.isValid():
                rows.append(_source_row(model, idx))
        if rows:
            src.prioritize_rows(rows)

    def _restart_prewarm(self, model):
        self._prewarm_pos = 0
        old = getattr(self, "_prewarm_dc_model", None)
        if old is not None:
            try:
                old.dataChanged.disconnect(self._on_prewarm_data_changed)
            except (TypeError, RuntimeError):
                pass
        self._prewarm_dc_model = model
        if model is not None:
            try:
                model.dataChanged.connect(self._on_prewarm_data_changed)
            except Exception:
                pass
            self._prewarm_timer.start()

    def _on_prewarm_data_changed(self, *_args):
        """Metadata arrives asynchronously — re-arm an idle prewarm pass.

        timer.start() on an active timer just restarts it, so bursts of
        dataChanged collapse into one pass.
        """
        self._prewarm_timer.start()

    def _prewarm_step(self):
        model = _source_model(self.model())
        if model is None or not hasattr(model, "CoverDataRole"):
            return
        count = model.rowCount()
        if count <= 0:
            return
        budget = 2          # thumbnails per idle tick — keeps each tick a few ms
        generated = 0
        scanned = 0
        while budget > 0 and scanned < count:
            row = self._prewarm_pos
            self._prewarm_pos = (self._prewarm_pos + 1) % count
            scanned += 1
            idx = model.index(row, 0)
            path = idx.data(model.FilePathRole)
            if not path or path in _cover_cache:
                continue
            if not idx.data(model.CoverDataRole):
                # lazy covers: bulk load skipped the bytes — fetch on idle
                meta = model.track_metadata(row) if hasattr(model, "track_metadata") else None
                if meta is not None and getattr(meta, "cover_data", None) is None:
                    from audio_player.player.metadata import ensure_cover
                    ensure_cover(path, meta)
                    generated += 1
                if not idx.data(model.CoverDataRole):
                    continue
            _thumbnail(model, idx, path)
            generated += 1
            budget -= 1
        if generated or scanned < count:
            self._prewarm_timer.start()  # more work or lap not yet complete
        # full lap with nothing to generate → stop; dataChanged re-arms later

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
