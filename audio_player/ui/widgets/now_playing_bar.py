"""Bottom now-playing bar — always visible mini player."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QFont, QPixmap, QPen

from audio_player.app import current_accent, current_theme_mode
from audio_player.ui.utils import format_duration, cover_corner_radius
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon,
)


class NowPlayingBar(QWidget):
    """Persistent bottom bar — cover | info | controls. Progress drawn as 1px top line."""

    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    seekRequested = pyqtSignal(float)  # ratio 0.0-1.0
    expandRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowPlayingBar")
        self.setFixedHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ratio = 0.0
        self._cover_pix = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 14, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # ── Cover ──
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(56, 56)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._cover_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # ── Info ──
        self._title_label = QLabel("VB Player")
        self._title_label.setObjectName("npTitle")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        self._title_label.setFont(f)

        self._artist_label = QLabel("")
        self._artist_label.setObjectName("npArtist")
        f2 = QFont()
        f2.setPointSize(9)
        self._artist_label.setFont(f2)

        layout.addWidget(self._title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._artist_label, 1, Qt.AlignmentFlag.AlignVCenter)

        # ── Controls ──
        prev_btn = QPushButton()
        prev_btn.setIcon(_icon(TRANSPORT_PREV, color="#999"))
        prev_btn.setObjectName("npBtn")
        prev_btn.setFixedSize(36, 36)
        prev_btn.clicked.connect(self.prevClicked.emit)
        layout.addWidget(prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._play_btn = QPushButton()
        self._play_btn.setIcon(_icon(TRANSPORT_PLAY, color="#fff"))
        self._play_btn.setObjectName("npPlayBtn")
        self._play_btn.setFixedSize(40, 40)
        self._play_btn.clicked.connect(self.playPauseClicked.emit)
        layout.addWidget(self._play_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        next_btn = QPushButton()
        next_btn.setIcon(_icon(TRANSPORT_NEXT, color="#999"))
        next_btn.setObjectName("npBtn")
        next_btn.setFixedSize(36, 36)
        next_btn.clicked.connect(self.nextClicked.emit)
        layout.addWidget(next_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        expand_btn = QPushButton("▲")
        expand_btn.setObjectName("npBtn")
        expand_btn.setFixedSize(28, 28)
        expand_btn.setToolTip("Now Playing")
        expand_btn.clicked.connect(self.expandRequested.emit)
        layout.addWidget(expand_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_style()

    def _apply_style(self):
        is_light = current_theme_mode() == "light"
        accent = current_accent()
        bar_bg = {"light": "#f5f5f5", "dark": "#1e1e1e"}[current_theme_mode()]
        title_c = "#1a1a1a" if is_light else "#eee"
        artist_c = "#666" if is_light else "#999"

        self.setStyleSheet(f"""
            QWidget#nowPlayingBar {{ background: {bar_bg}; border: none; }}
            QLabel#npTitle {{ color: {title_c}; }}
            QLabel#npArtist {{ color: {artist_c}; }}
            QPushButton#npBtn {{
                background: transparent; border: none; border-radius: 18px;
                color: {artist_c}; font-size: 14px;
            }}
            QPushButton#npBtn:hover {{
                background: {"rgba(0,0,0,0.06)" if is_light else "rgba(255,255,255,0.08)"};
            }}
            QPushButton#npPlayBtn {{
                background: {accent.name()}; color: #fff;
                border: none; border-radius: 20px;
            }}
            QPushButton#npPlayBtn:hover {{
                background: {accent.lighter(120).name()};
            }}
        """)

    # ── Public API ──

    def update_cover(self, cover_data: bytes | None):
        if cover_data:
            pix = QPixmap()
            pix.loadFromData(cover_data)
            if not pix.isNull():
                raw = pix.scaled(56, 56,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                # Render rounded based on setting
                from PyQt6.QtGui import QPainterPath
                r = cover_corner_radius()
                rounded = QPixmap(56, 56)
                rounded.fill(Qt.GlobalColor.transparent)
                p = QPainter(rounded)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(0, 0, 56, 56, r, r)
                p.setClipPath(path)
                p.drawPixmap((56 - raw.width()) // 2, (56 - raw.height()) // 2, raw)
                p.end()
                self._cover_label.setPixmap(rounded)
                return
        self._cover_pix = None
        self._cover_label.setText("")

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
        self._ratio = ms / max(self._duration_ms, 1)
        self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms if ms > 0 else 1

    def refresh_theme(self):
        self._apply_style()
        self.update()

    def refresh_accent(self):
        self._apply_style()
        self.update()

    # ── Paint progress line ──

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        # 1px progress line at top edge
        # Unfilled portion
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 20) if current_theme_mode() != "light"
                   else QColor(0, 0, 0, 12))
        p.drawRect(0, 0, w, 1)

        # Filled portion
        if self._ratio > 0:
            accent = current_accent()
            p.setBrush(accent)
            p.drawRect(0, 0, int(w * self._ratio), 1)

        p.end()

    def mouseReleaseEvent(self, e: QMouseEvent):
        child = self.childAt(e.pos())
        from PyQt6.QtWidgets import QPushButton
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseReleaseEvent(e)
