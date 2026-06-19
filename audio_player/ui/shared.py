"""Shared Qt types reused across multiple widget modules.

Moved here from album_view.py to eliminate the circular-ish dependency
where playlist_browse.py imported private symbols from album_view.py.
"""

from PyQt6.QtWidgets import (
    QLayout, QStyledItemDelegate, QStyle, QListView,
)
from PyQt6.QtCore import Qt, QRect, QSize, QModelIndex, QAbstractListModel
from PyQt6.QtGui import QPainter, QColor, QFont

from audio_player.app import current_accent
from audio_player.ui.icons import ALBUM_PLACEHOLDER, _icon
from audio_player.ui.utils import is_light_mode


# ---------------------------------------------------------------------------
# Placeholder icon helper
# ---------------------------------------------------------------------------

def set_placeholder_icon(label, size: int = 48):
    """Set a placeholder album icon on a QLabel."""
    from PyQt6.QtWidgets import QLabel
    pixmap = _icon(ALBUM_PLACEHOLDER, color="#555555").pixmap(size, size)
    label.setPixmap(pixmap)


# ---------------------------------------------------------------------------
# Flow layout — wraps child widgets when width is insufficient
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=-1):
        super().__init__(parent)
        self._items: list = []
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
# Album track list model + delegate (used by album_view and playlist_browse)
# ---------------------------------------------------------------------------

class AlbumTrackModel(QAbstractListModel):
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


class AlbumTrackDelegate(QStyledItemDelegate):
    MARGIN = 2

    def paint(self, painter: QPainter, option, index: QModelIndex):
        model = index.model()
        is_header = model.data(index, AlbumTrackModel.HeaderRole)

        if is_header:
            self._paint_header(painter, option, index)
        else:
            self._paint_track(painter, option, index)

    def _paint_header(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        rect = option.rect
        light = is_light_mode()
        color = QColor("#999999") if light else QColor("#555555")
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
        light = is_light_mode()
        accent = current_accent()

        # Selection background
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            c = QColor(accent)
            c.setAlpha(40)
            painter.setBrush(c)
            painter.drawRoundedRect(rect, 6, 6)

        # Current playing indicator
        is_current = bool(model.data(index, AlbumTrackModel.IsCurrentRole))
        if is_current:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(
                QRect(rect.x() + 4, rect.y() + 8, 3, rect.height() - 16), 1.5, 1.5)

        # Track number
        track_num = model.data(index, AlbumTrackModel.TrackNumRole) or 0
        num_font = QFont(painter.font())
        num_font.setPointSize(9)
        painter.setFont(num_font)
        painter.setPen(accent if is_current else QColor("#64748b"))
        tn_str = f"{track_num:02d}" if track_num else "??"
        painter.drawText(QRect(rect.x() + 9, rect.y(), 30, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, tn_str)

        # Text area
        text_x = rect.x() + 50
        text_w = rect.width() - 50 - 8

        title = model.data(index, AlbumTrackModel.TitleRole) or "Unknown"
        artist = model.data(index, AlbumTrackModel.ArtistRole) or ""
        dur_sec = model.data(index, AlbumTrackModel.DurationRole) or 0

        # Title
        title_font = QFont(painter.font())
        title_font.setPointSize(10)
        title_font.setBold(is_current)
        painter.setFont(title_font)
        title_color = QColor("#333333") if light else QColor("#e2e8f0")
        painter.setPen(accent.lighter(130) if is_current else title_color)
        title_text = painter.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, rect.y() + 4, text_w, 20,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, title_text)

        # Artist + Duration
        sub_font = QFont(painter.font())
        sub_font.setPointSize(9)
        painter.setFont(sub_font)
        painter.setPen(QColor("#888888") if light else QColor("#64748b"))
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
        if model and model.data(index, AlbumTrackModel.HeaderRole):
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
