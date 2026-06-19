"""Bottom now-playing bar — always visible mini player."""

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtGui import QFont, QPixmap

from audio_player.app import current_accent, current_theme_mode
from audio_player.ui.utils import format_duration
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon,
)


class NowPlayingBar(QWidget):
    """Persistent bottom bar showing current track + mini controls."""

    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    seekRequested = pyqtSignal(int)       # position in ms
    expandRequested = pyqtSignal()        # go to Now Playing page

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowPlayingBar")
        self.setFixedHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._duration_ms = 0
        self._position_ms = 0
        self._dragging = False
        self._cover_pix = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # Cover art thumbnail
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(48, 48)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._cover_label)

        # Track info + mini progress
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 2, 0, 2)
        info_layout.setSpacing(2)

        text_row = QHBoxLayout()
        self._title_label = QLabel("VB Player")
        self._title_label.setObjectName("npTitle")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        self._title_label.setFont(f)
        text_row.addWidget(self._title_label)
        text_row.addStretch()
        self._time_label = QLabel("")
        self._time_label.setObjectName("npTime")
        tf = QFont()
        tf.setPointSize(9)
        self._time_label.setFont(tf)
        text_row.addWidget(self._time_label)
        info_layout.addLayout(text_row)

        self._artist_label = QLabel("")
        self._artist_label.setObjectName("npArtist")
        f2 = QFont()
        f2.setPointSize(9)
        self._artist_label.setFont(f2)
        info_layout.addWidget(self._artist_label)

        # Mini progress bar
        from PyQt6.QtWidgets import QSlider
        self._progress = QSlider(Qt.Orientation.Horizontal)
        self._progress.setObjectName("npProgress")
        self._progress.setRange(0, 1000)
        self._progress.setFixedHeight(4)
        self._progress.sliderReleased.connect(
            lambda: self.seekRequested.emit(self._progress.value()))
        info_layout.addWidget(self._progress)

        layout.addWidget(info_widget, 1)

        # Transport controls
        prev_btn = QPushButton()
        prev_btn.setIcon(_icon(TRANSPORT_PREV, color="#999"))
        prev_btn.setObjectName("npBtn")
        prev_btn.setFixedSize(36, 36)
        prev_btn.clicked.connect(self.prevClicked.emit)
        layout.addWidget(prev_btn)

        self._play_btn = QPushButton()
        self._play_btn.setIcon(_icon(TRANSPORT_PLAY, color="#fff"))
        self._play_btn.setObjectName("npPlayBtn")
        self._play_btn.setFixedSize(40, 40)
        self._play_btn.clicked.connect(self.playPauseClicked.emit)
        layout.addWidget(self._play_btn)

        next_btn = QPushButton()
        next_btn.setIcon(_icon(TRANSPORT_NEXT, color="#999"))
        next_btn.setObjectName("npBtn")
        next_btn.setFixedSize(36, 36)
        next_btn.clicked.connect(self.nextClicked.emit)
        layout.addWidget(next_btn)

        # Expand button
        expand_btn = QPushButton("▲")
        expand_btn.setObjectName("npBtn")
        expand_btn.setFixedSize(28, 28)
        expand_btn.setToolTip("Now Playing")
        expand_btn.clicked.connect(self.expandRequested.emit)
        layout.addWidget(expand_btn)

        self._apply_style()

    def _apply_style(self):
        is_light = current_theme_mode() == "light"
        bar_bg = "#f0f0f0" if is_light else "#1a1a1a"
        bar_border = "#d0d0d0" if is_light else "#2a2a2a"
        title_c = "#1a1a1a" if is_light else "#eee"
        artist_c = "#666" if is_light else "#999"

        self.setStyleSheet(f"""
            QWidget#nowPlayingBar {{
                background: {bar_bg};
                border-top: 1px solid {bar_border};
            }}
            QLabel#npTitle {{ color: {title_c}; }}
            QLabel#npArtist {{ color: {artist_c}; }}
            QLabel#npTime {{ color: {artist_c}; font-size: 9px; }}
            QPushButton#npBtn {{
                background: transparent; border: none; border-radius: 18px;
                color: {artist_c}; font-size: 14px;
            }}
            QPushButton#npBtn:hover {{ background: {"#ddd" if is_light else "#333"}; }}
            QPushButton#npPlayBtn {{
                background: {current_accent().name()}; color: #fff;
                border: none; border-radius: 20px;
            }}
            QPushButton#npPlayBtn:hover {{
                background: {current_accent().lighter(120).name()};
            }}
            QSlider#npProgress::groove:horizontal {{
                background: {"#ddd" if is_light else "#333"}; height: 3px; border-radius: 1px;
            }}
            QSlider#npProgress::sub-page:horizontal {{
                background: {current_accent().name()}; border-radius: 1px;
            }}
            QSlider#npProgress::handle:horizontal {{
                background: {current_accent().name()}; width: 10px; height: 10px;
                border-radius: 5px; margin: -4px 0;
            }}
        """)

    def update_cover(self, cover_data: bytes | None):
        if cover_data:
            pix = QPixmap()
            pix.loadFromData(cover_data)
            self._cover_pix = pix.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
        else:
            self._cover_pix = None
        self._render_cover()

    def _render_cover(self):
        try:
            if self._cover_pix and not self._cover_pix.isNull():
                scaled = self._cover_pix.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)
                self._cover_label.setPixmap(scaled)
            else:
                self._cover_label.setText("🎵")
        except Exception:
            self._cover_label.setText("🎵")

    def set_track(self, title: str, artist: str, album: str = ""):
        self._title_label.setText(title or "Unknown")
        line2 = artist
        if album and album != artist:
            line2 = f"{artist} — {album}" if artist else album
        self._artist_label.setText(line2)

    def set_playing(self, playing: bool):
        icon = TRANSPORT_PAUSE if playing else TRANSPORT_PLAY
        self._play_btn.setIcon(_icon(icon, color="#fff"))

    def set_position(self, ms: int):
        self._position_ms = ms
        if not self._progress.isSliderDown():
            self._progress.blockSignals(True)
            self._progress.setValue(ms)
            self._progress.blockSignals(False)
        self._time_label.setText(format_duration(ms / 1000) if ms > 0 else "")

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self._progress.setRange(0, ms if ms > 0 else 1)

    def refresh_theme(self):
        self._apply_style()

    def refresh_accent(self):
        self._apply_style()

    def mouseReleaseEvent(self, e: QMouseEvent):
        """Click anywhere on the bar to expand."""
        child = self.childAt(e.pos())
        # Expand when clicking the cover, labels, or empty space — not buttons
        from PyQt6.QtWidgets import QPushButton
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseReleaseEvent(e)
