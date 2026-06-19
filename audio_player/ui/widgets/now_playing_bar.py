"""Bottom now-playing bar — compact, controls centered, time right."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QFont, QPixmap, QPen

from audio_player.app import current_accent, current_theme_mode
from audio_player.ui.utils import format_duration, cover_corner_radius
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon,
)


class NowPlayingBar(QWidget):
    """Bottom bar — cover·info | controls | time. Progress painted as 3px top line."""

    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    expandRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowPlayingBar")
        self.setFixedHeight(68)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ratio = 0.0
        self._duration_ms = 1
        self._position_ms = 0
        self._cover_pix = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # ── Left: cover + info ──
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(48, 48)
        layout.addWidget(self._cover_label, 0, Qt.AlignmentFlag.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(0)
        self._title_label = QLabel("VB Player")
        self._title_label.setObjectName("npTitle")
        f = QFont(); f.setPointSize(10); f.setBold(True); self._title_label.setFont(f)
        info.addWidget(self._title_label)
        self._artist_label = QLabel("")
        self._artist_label.setObjectName("npArtist")
        f2 = QFont(); f2.setPointSize(8); self._artist_label.setFont(f2)
        info.addWidget(self._artist_label)
        layout.addLayout(info)

        # ── Center: controls ──
        layout.addStretch()
        prev_btn = QPushButton()
        prev_btn.setIcon(_icon(TRANSPORT_PREV, color="#999"))
        prev_btn.setObjectName("npBtn")
        prev_btn.setFixedSize(36, 36)
        prev_btn.clicked.connect(self.prevClicked.emit)
        layout.addWidget(prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._play_btn = QPushButton()
        self._play_btn.setIcon(_icon(TRANSPORT_PLAY, color="#fff"))
        self._play_btn.setObjectName("npPlayBtn")
        self._play_btn.setFixedSize(42, 42)
        self._play_btn.clicked.connect(self.playPauseClicked.emit)
        layout.addWidget(self._play_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        next_btn = QPushButton()
        next_btn.setIcon(_icon(TRANSPORT_NEXT, color="#999"))
        next_btn.setObjectName("npBtn")
        next_btn.setFixedSize(36, 36)
        next_btn.clicked.connect(self.nextClicked.emit)
        layout.addWidget(next_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch()

        # ── Right: time ──
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setObjectName("npTime")
        tf = QFont(); tf.setPointSize(9); tf.setFamily("monospace")
        self._time_label.setFont(tf)
        layout.addWidget(self._time_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_style()

    def _apply_style(self):
        is_light = current_theme_mode() == "light"
        accent = current_accent()
        bar_bg = {"light": "#f5f5f5", "dark": "#1e1e1e"}[current_theme_mode()]
        title_c = "#1a1a1a" if is_light else "#eee"
        sub_c = "#666" if is_light else "#999"

        self.setStyleSheet(f"""
            QWidget#nowPlayingBar {{ background: {bar_bg}; border: none; }}
            QLabel#npTitle {{ color: {title_c}; }}
            QLabel#npArtist {{ color: {sub_c}; }}
            QLabel#npTime {{ color: {sub_c}; }}
            QPushButton#npBtn {{
                background: transparent; border: none; border-radius: 18px;
                color: {sub_c}; font-size: 14px;
            }}
            QPushButton#npBtn:hover {{
                background: {"rgba(0,0,0,0.06)" if is_light else "rgba(255,255,255,0.08)"};
            }}
            QPushButton#npPlayBtn {{
                background: {accent.name()}; color: #fff;
                border: none; border-radius: 21px;
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
                raw = pix.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                from PyQt6.QtGui import QPainterPath
                r = cover_corner_radius()
                rounded = QPixmap(48, 48)
                rounded.fill(Qt.GlobalColor.transparent)
                p = QPainter(rounded); p.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(0, 0, 40, 40, r, r)
                p.setClipPath(path)
                p.drawPixmap((48 - raw.width()) // 2, (48 - raw.height()) // 2, raw)
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

    # ── Paint 3px progress line ──

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        w = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        # Groove: full width, 3px
        p.setBrush(QColor(0,0,0,20) if current_theme_mode() != "light" else QColor(0,0,0,10))
        p.drawRect(0, 0, w, 3)
        # Filled: accent
        if self._ratio > 0:
            p.setBrush(current_accent())
            p.drawRect(0, 0, int(w * self._ratio), 3)
        p.end()

    def mouseReleaseEvent(self, e: QMouseEvent):
        child = self.childAt(e.pos())
        from PyQt6.QtWidgets import QPushButton
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseReleaseEvent(e)
