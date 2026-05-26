from PyQt6.QtWidgets import (QListView, QStyledItemDelegate, QStyle,
                             QAbstractItemView)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect, QModelIndex, QSettings
from PyQt6.QtGui import QPainter, QColor, QPen, QFont


def _accent_color() -> QColor:
    s = QSettings("VBPlayer", "VB Player")
    name = str(s.value("accent", "purple") or "purple")
    accents = {
        "purple": QColor("#7c3aed"),
        "blue":   QColor("#007AFF"),
        "green":  QColor("#10b981"),
        "orange": QColor("#f59e0b"),
        "pink":   QColor("#ec4899"),
        "red":    QColor("#ef4444"),
    }
    return accents.get(name, QColor("#7c3aed"))


class _PlaylistDelegate(QStyledItemDelegate):
    MARGIN = 3

    def paint(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(self.MARGIN, 2, -self.MARGIN, -2)
        is_selected = option.state & QStyle.StateFlag.State_Selected
        model = index.model()
        row = index.row()
        accent = _accent_color()

        # Background
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            c = QColor(accent)
            c.setAlpha(40)
            painter.setBrush(c)
            painter.drawRoundedRect(rect, 6, 6)

        # Playing indicator
        is_current = model and model.current_index == row
        if is_current:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRect(rect.x() + 4, rect.y() + 8, 3, rect.height() - 16), 1.5, 1.5)

        # Track number
        num_font = QFont(painter.font())
        num_font.setPointSize(9)
        painter.setFont(num_font)
        painter.setPen(QColor("#64748b") if not is_current else accent)
        painter.drawText(QRect(rect.x() + 14, rect.y(), 28, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, str(row + 1))

        # Text
        text_x = rect.x() + 44
        text_w = rect.width() - 44 - 50

        title = (index.data(model.TitleRole) if model else "") or "Unknown"
        artist = (index.data(model.ArtistRole) if model else "") or ""
        dur_sec = (index.data(model.DurationRole) if model else 0) or 0

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
        filepath = (index.data(model.FilePathRole) if model else "") or ""
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

        self.clicked.connect(self._on_click)
        self.doubleClicked.connect(self._on_double_click)

    def _on_click(self, idx: QModelIndex):
        self.trackClicked.emit(idx.row())

    def _on_double_click(self, idx: QModelIndex):
        self.trackDoubleClicked.emit(idx.row())

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
