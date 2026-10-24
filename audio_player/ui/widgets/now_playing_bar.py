"""Bottom now-playing bar — symmetrical: cover+info left, controls centered, time right."""

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QSlider)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QFont, QPixmap

from audio_player.app import current_accent, current_theme_mode, surface_translucent
from audio_player.i18n import _
from audio_player.ui.utils import format_duration, cover_corner_radius
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT,
    VOLUME_MUTED, VOLUME_LOW, VOLUME_HIGH, _icon,
)

LEFT_RIGHT_MIN_W = 220  # ensures left/right sections balance each other


class NowPlayingBar(QWidget):
    """Bottom bar with true-centered controls and symmetric left/right sections."""

    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    expandRequested = pyqtSignal()
    volumeChanged = pyqtSignal(float)   # 0.0 - 1.0, user-initiated
    muteToggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowPlayingBar")
        self.setFixedHeight(84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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

        # ── Right: volume + time (mirrors left section weight) ──
        right_container = QWidget()
        right_container.setMinimumWidth(LEFT_RIGHT_MIN_W)
        right = QHBoxLayout(right_container)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._vol_btn = QPushButton()
        self._vol_btn.setObjectName("npBtn")
        self._vol_btn.setIcon(_icon(VOLUME_HIGH, color="#999"))
        self._vol_btn.setFixedSize(36, 36)
        self._vol_btn.setToolTip(_("volume.title"))
        self._vol_btn.clicked.connect(self.muteToggled.emit)
        right.addWidget(self._vol_btn)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setObjectName("volSlider")
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(96)
        self._vol_slider.setToolTip(_("volume.title"))
        self._vol_slider.valueChanged.connect(
            lambda v: self.volumeChanged.emit(v / 100.0))
        right.addWidget(self._vol_slider)
        right.addSpacing(14)

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
        if surface_translucent():
            bar_bg = "rgba(250,250,250,205)" if is_light else "rgba(30,30,30,170)"
        else:
            bar_bg = "#f5f5f5" if is_light else "#1e1e1e"
        title_c = "#1a1a1a" if is_light else "#eee"
        sub_c = "#666" if is_light else "#aaa"
        groove = "#d0d0d0" if is_light else "#3a3a3a"

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
                background: {"#0f000000" if is_light else "#14ffffff"};
            }}
            QPushButton#npPlayBtn {{
                background: {accent.name()}; color: #fff;
                border: none; border-radius: 28px;
            }}
            QPushButton#npPlayBtn:hover {{
                background: {accent.lighter(120).name()};
            }}
            QSlider#volSlider {{ background: transparent; height: 20px; }}
            QSlider#volSlider::groove:horizontal {{
                background: {groove}; height: 4px; border-radius: 2px;
            }}
            QSlider#volSlider::sub-page:horizontal {{
                background: {accent.name()}; border-radius: 2px;
            }}
            QSlider#volSlider::handle:horizontal {{
                background: {"#ffffff"}; width: 12px; height: 12px;
                border-radius: 6px; margin: -4px 0;
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
        self._time_label.setText(f"{format_duration(ms/1000)} / {format_duration(self._duration_ms/1000)}")

    def set_duration(self, ms: int):
        self._duration_ms = ms if ms > 0 else 1
        self._time_label.setText(f"0:00 / {format_duration(ms/1000)}")

    def set_volume(self, vol: float, muted: bool = False):
        """Update the volume UI from the engine (no user-echo back)."""
        vol = max(0.0, min(1.0, float(vol)))
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(int(round(vol * 100)))
        self._vol_slider.blockSignals(False)
        if muted or vol <= 0.0:
            icon_name = VOLUME_MUTED
        elif vol < 0.5:
            icon_name = VOLUME_LOW
        else:
            icon_name = VOLUME_HIGH
        is_light = current_theme_mode() == "light"
        self._vol_btn.setIcon(_icon(icon_name, color="#333" if is_light else "#999"))

    def wheelEvent(self, event):
        """Scroll anywhere on the bar = volume ±5% (Apple Music behavior)."""
        dy = event.angleDelta().y()
        if dy:
            step = 0.05 if dy > 0 else -0.05
            self.volumeChanged.emit(
                max(0.0, min(1.0, self._vol_slider.value() / 100.0 + step)))
        super().wheelEvent(event)

    def refresh_theme(self): self._apply_style(); self.update()
    def refresh_accent(self): self._apply_style(); self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        child = self.childAt(e.pos())
        from PyQt6.QtWidgets import QPushButton
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseReleaseEvent(e)
