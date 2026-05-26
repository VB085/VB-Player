from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFrame,
                             QScrollArea, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QPixmap, QColor

from .cover_art import CoverArtWidget


def _accent_light_hex() -> str:
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
    return accents.get(name, QColor("#7c3aed")).lighter(130).name()


def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


class MetadataPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("metadataPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        self._cover = CoverArtWidget()
        self._cover.setMinimumSize(220, 220)
        self._cover.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(12)

        self._title_label = QLabel("No Track")
        self._title_label.setObjectName("title")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._artist_label = QLabel("")
        self._artist_label.setObjectName("subtitle")
        self._artist_label.setWordWrap(True)
        layout.addWidget(self._artist_label)

        self._album_label = QLabel("")
        self._album_label.setObjectName("infoLabel")
        self._album_label.setWordWrap(True)
        layout.addWidget(self._album_label)

        layout.addSpacing(8)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        layout.addSpacing(4)

        def add_info_row(label, value_widget):
            hl = QVBoxLayout()
            hl.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(label)
            lbl.setObjectName("sectionHeader")
            hl.addWidget(lbl)
            hl.addWidget(value_widget)
            layout.addLayout(hl)

        self._duration_label = QLabel("--:--")
        self._duration_label.setObjectName("infoLabel")
        add_info_row("DURATION", self._duration_label)

        self._format_label = QLabel("")
        self._format_label.setObjectName("infoLabel")
        add_info_row("FORMAT", self._format_label)

        self._quality_label = QLabel("")
        self._quality_label.setObjectName("infoLabel")
        add_info_row("QUALITY", self._quality_label)

        self._file_size_label = QLabel("")
        self._file_size_label.setObjectName("infoLabel")
        add_info_row("SIZE", self._file_size_label)

        self._year_label = QLabel("")
        self._year_label.setObjectName("infoLabel")
        add_info_row("YEAR", self._year_label)

        self._genre_label = QLabel("")
        self._genre_label.setObjectName("infoLabel")
        add_info_row("GENRE", self._genre_label)

        layout.addStretch()

    def show_metadata(self, meta, filepath: str = ""):
        if meta is None:
            self._title_label.setText("Unknown")
            self._artist_label.setText("")
            self._album_label.setText("")
            self._duration_label.setText("--:--")
            self._format_label.setText("")
            self._quality_label.setText("")
            self._file_size_label.setText("")
            self._year_label.setText("")
            self._genre_label.setText("")
            self._cover.set_cover(None)
            return

        title = meta.title or "Unknown"
        self._title_label.setText(title)
        self._artist_label.setText(meta.artist or "Unknown Artist")
        self._album_label.setText(meta.album or "")
        self._duration_label.setText(_format_duration(meta.duration_seconds))
        self._format_label.setText(meta.format or "—")
        quality_parts = []
        if meta.sample_rate:
            quality_parts.append(f"{meta.sample_rate / 1000:.1f} kHz")
        if meta.bits_per_sample:
            quality_parts.append(f"{meta.bits_per_sample} bit")
        if meta.bitrate:
            quality_parts.append(f"{meta.bitrate} kbps")
        if meta.channels:
            ch_map = {1: "Mono", 2: "Stereo"}
            quality_parts.append(ch_map.get(meta.channels, f"{meta.channels}ch"))
        self._quality_label.setText(" / ".join(quality_parts) if quality_parts else "—")
        self._file_size_label.setText(_format_size(meta.file_size) if meta.file_size else "—")
        self._year_label.setText(str(meta.year) if meta.year else "—")
        self._genre_label.setText(meta.genre if meta.genre else "—")
        self._cover.set_cover(meta.cover_data, title)

    def clear(self):
        self.show_metadata(None)

    def _apply_style(self):
        accent = _accent_light_hex()
        self.setStyleSheet(
            f"QLabel#title{{color:#ffffff;font-size:15px;font-weight:bold;}}"
            f"QLabel#subtitle{{color:{accent};font-size:12px;}}"
            f"QLabel#infoLabel{{color:#94a3b8;font-size:11px;}}"
            f"QLabel#sectionHeader{{color:#64748b;font-size:10px;font-weight:bold;letter-spacing:2px;"
            f"text-transform:uppercase;margin-top:16px;margin-bottom:4px;}}"
            f"QFrame#separator{{background:#252540;max-height:1px;margin:8px 0;}}"
        )

    def refresh_accent(self):
        self._apply_style()
