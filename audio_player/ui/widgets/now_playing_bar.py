"""Bottom now-playing bar — symmetrical: cover+info left, controls centered, time right."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QFont, QPixmap

from audio_player.app import current_accent, current_theme_mode
from audio_player.ui.utils import format_duration, cover_corner_radius
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon,
)

LEFT_RIGHT_MIN_W = 220  # ensures left/right sections balance each other


class NowPlayingBar(QWidget):
    """Bottom bar with true-centered controls and symmetric left/right sections."""

    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    expandRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowPlayingBar")
        self.setFixedHeight(84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ratio = 0.0
        self._duration_ms = 1
        self._position_ms = 0
        self._cover_pix = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 4, 20, 0)
        layout.setSpacing(0)

        # ── Left: cover + info ──
        left_container = QWidget()
        left_container.setMinimumWidth(LEFT_RIGHT_MIN_W)
        left = QHBoxLayout(left_container)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)
        left.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(56, 56)
        left.addWidget(self._cover_label)

        info = QVBoxLayout()
        info.setSpacing(3)
        self._title_label = QLabel("VB Player")
        self._title_label.setObjectName("npTitle")
        f = QFont(); f.setPointSize(12); f.setBold(True); self._title_label.setFont(f)
        info.addWidget(self._title_label)
        self._artist_label = QLabel("")
        self._artist_label.setObjectName("npArtist")
        f2 = QFont(); f2.setPointSize(10); self._artist_label.setFont(f2)
        info.addWidget(self._artist_label)
        left.addLayout(info, 1)
        layout.addWidget(left_container)

        # ── Center: controls, truly centered in remaining space ──
        layout.addStretch(1)

        prev_btn = QPushButton()
        prev_btn.setIcon(_icon(TRANSPORT_PREV, color="#999"))
        prev_btn.setObjectName("npBtn")
        prev_btn.setFixedSize(48, 48)
        prev_btn.clicked.connect(self.prevClicked.emit)
        layout.addWidget(prev_btn)

        layout.addSpacing(10)

        self._play_btn = QPushButton()
        self._play_btn.setIcon(_icon(TRANSPORT_PLAY, color="#fff"))
        self._play_btn.setObjectName("npPlayBtn")
        self._play_btn.setFixedSize(56, 56)
        self._play_btn.clicked.connect(self.playPauseClicked.emit)
        layout.addWidget(self._play_btn)

        layout.addSpacing(10)

        next_btn = QPushButton()
        next_btn.setIcon(_icon(TRANSPORT_NEXT, color="#999"))
        next_btn.setObjectName("npBtn")
        next_btn.setFixedSize(48, 48)
        next_btn.clicked.connect(self.nextClicked.emit)
        layout.addWidget(next_btn)

        layout.addStretch(1)

        # ── Right: time (mirrors left section weight) ──
        right_container = QWidget()
        right_container.setMinimumWidth(LEFT_RIGHT_MIN_W)
        right = QHBoxLayout(right_container)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setObjectName("npTime")
        tf = QFont(); tf.setPointSize(11); tf.setFamily("monospace")
        self._time_label.setFont(tf)
        right.addWidget(self._time_label)
        layout.addWidget(right_container)

        self._apply_style()

    def _apply_style(self):
        is_light = current_theme_mode() == "light"
        accent = current_accent()
        bar_bg = "#f5f5f5" if is_light else "#1e1e1e"
        title_c = "#1a1a1a" if is_light else "#eee"
        sub_c = "#666" if is_light else "#aaa"

        self.setStyleSheet(f"""
            QWidget#nowPlayingBar {{ background: {bar_bg}; border: none; }}
            QLabel#npTitle {{ color: {title_c}; }}
            QLabel#npArtist {{ color: {sub_c}; }}
            QLabel#npTime {{ color: {sub_c}; }}
            QPushButton#npBtn {{
                background: transparent; border: none; border-radius: 24px;
                color: {sub_c}; font-size: 20px;
            }}
            QPushButton#npBtn:hover {{
                background: {"rgba(0,0,0,0.06)" if is_light else "rgba(255,255,255,0.08)"};
            }}
            QPushButton#npPlayBtn {{
                background: {accent.name()}; color: #fff;
                border: none; border-radius: 28px;
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
                raw = pix.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                from PyQt6.QtGui import QPainterPath
                r = cover_corner_radius()
                rounded = QPixmap(56, 56)
                rounded.fill(Qt.GlobalColor.transparent)
                p = QPainter(rounded); p.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(0, 0, 48, 48, r, r)
                p.setClipPath(path)
                p.drawPixmap((56 - raw.width()) // 2, (56 - raw.height()) // 2, raw)
                p.end()
                self._cover_label.setPixmap(rounded)
                return
        self._cover_label.setText("")

    def set_track(self, title: str, artist: str, album: str = ""):
        self._title_label.setText(title or "Unknown")
        parts = [artist] if artist else []
        if album and album != artist:
            parts.append(album)
        self._artist_label.setText(" — ".join(parts) if parts else "")

    def set_playing(self, playing: bool):
        icon = TRANSPORT_PAUSE if playing else TRANSPORT_PLAY
        self._play_btn.setIcon(_icon(icon, color="#fff"))

    def set_position(self, ms: int):
        self._position_ms = ms
        self._ratio = ms / self._duration_ms if self._duration_ms > 0 else 0
        self._time_label.setText(f"{format_duration(ms/1000)} / {format_duration(self._duration_ms/1000)}")
        self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms if ms > 0 else 1
        self._time_label.setText(f"0:00 / {format_duration(ms/1000)}")

    def refresh_theme(self): self._apply_style(); self.update()
    def refresh_accent(self): self._apply_style(); self.update()

    # ── Paint 4px progress line ──

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        w = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        # Groove: full width, 4px
        p.setBrush(QColor(0,0,0,20) if current_theme_mode() != "light" else QColor(0,0,0,10))
        p.drawRect(0, 0, w, 4)
        # Filled: accent
        if self._ratio > 0:
            p.setBrush(current_accent())
            p.drawRect(0, 0, int(w * self._ratio), 4)
        p.end()

    def mouseReleaseEvent(self, e: QMouseEvent):
        child = self.childAt(e.pos())
        from PyQt6.QtWidgets import QPushButton
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseReleaseEvent(e)
