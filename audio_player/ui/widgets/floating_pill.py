"""Floating pill — Apple Music-style centered playback capsule."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QFont, QPixmap, QPainterPath

from audio_player.app import current_accent, current_theme_mode
from audio_player.ui.utils import format_duration
from audio_player.ui.icons import (
    TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon,
)

PILL_W = 580
PILL_H = 72
COVER_SIZE = 40


class FloatingPill(QWidget):
    """Centered floating playback capsule — glass background, cover, progress bar."""

    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()        # unused but kept for API compatibility
    expandRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("floatingPill")
        self.setFixedHeight(PILL_H)
        self.setMaximumWidth(PILL_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ratio = 0.0
        self._duration_ms = 1
        self._position_ms = 0
        self._title = ""
        self._artist = ""

        self.setup_ui()
        self._apply_style()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Cover
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(COVER_SIZE, COVER_SIZE)
        layout.addWidget(self._cover_label)

        # Track info
        info = QVBoxLayout()
        info.setSpacing(1)
        self._title_label = QLabel("VB Player")
        self._title_label.setObjectName("pillTitle")
        f = QFont(); f.setPointSize(11); f.setBold(True); self._title_label.setFont(f)
        info.addWidget(self._title_label)
        self._artist_label = QLabel("")
        self._artist_label.setObjectName("pillArtist")
        f2 = QFont(); f2.setPointSize(9); self._artist_label.setFont(f2)
        info.addWidget(self._artist_label)
        layout.addLayout(info, 1)

        # Play
        self._play_btn = QPushButton()
        self._play_btn.setIcon(_icon(TRANSPORT_PLAY, color="#fff"))
        self._play_btn.setObjectName("pillPlayBtn")
        self._play_btn.setFixedSize(40, 40)
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.clicked.connect(self.playPauseClicked.emit)
        layout.addWidget(self._play_btn)

        # Next
        next_btn = QPushButton()
        next_btn.setIcon(_icon(TRANSPORT_NEXT, color="#999"))
        next_btn.setObjectName("pillBtn")
        next_btn.setFixedSize(36, 36)
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.clicked.connect(self.nextClicked.emit)
        layout.addWidget(next_btn)

    def _apply_style(self):
        is_light = current_theme_mode() == "light"
        accent = current_accent()
        title_c = "#1a1a1a" if is_light else "#eee"
        sub_c = "#666" if is_light else "#aaa"

        # Background uses paintEvent for glass fill — QSS only for child widgets
        self.setStyleSheet(f"""
            QWidget#floatingPill {{ background: transparent; }}
            QLabel#pillTitle {{ color: {title_c}; }}
            QLabel#pillArtist {{ color: {sub_c}; }}
            QPushButton#pillBtn {{
                background: transparent; border: none; border-radius: 18px;
                color: {sub_c}; font-size: 16px;
            }}
            QPushButton#pillBtn:hover {{
                background: {"rgba(0,0,0,0.06)" if is_light else "rgba(255,255,255,0.08)"};
            }}
            QPushButton#pillPlayBtn {{
                background: {accent.name()}; color: #fff;
                border: none; border-radius: 20px;
            }}
            QPushButton#pillPlayBtn:hover {{
                background: {accent.lighter(115).name()};
            }}
        """)

    # ── Public API (mirrors NowPlayingBar) ──

    def update_cover(self, cover_data: bytes | None):
        if cover_data:
            pix = QPixmap()
            pix.loadFromData(cover_data)
            if not pix.isNull():
                scaled = pix.scaled(COVER_SIZE, COVER_SIZE,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                # Rounded clip
                rounded = QPixmap(COVER_SIZE, COVER_SIZE)
                rounded.fill(Qt.GlobalColor.transparent)
                p = QPainter(rounded); p.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(0, 0, COVER_SIZE, COVER_SIZE, 6, 6)
                p.setClipPath(path)
                p.drawPixmap((COVER_SIZE - scaled.width()) // 2,
                             (COVER_SIZE - scaled.height()) // 2, scaled)
                p.end()
                self._cover_label.setPixmap(rounded)
                return
        self._cover_label.clear()

    def set_track(self, title: str, artist: str, album: str = ""):
        self._title_label.setText(title or "Unknown")
        parts = [artist] if artist else []
        if album and album != artist:
            parts.append(album)
        self._artist_label.setText(" · ".join(parts) if parts else "")

    def set_playing(self, playing: bool):
        icon = TRANSPORT_PAUSE if playing else TRANSPORT_PLAY
        self._play_btn.setIcon(_icon(icon, color="#fff"))

    def set_position(self, ms: int):
        self._position_ms = ms
        self._ratio = ms / self._duration_ms if self._duration_ms > 0 else 0
        self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms if ms > 0 else 1

    def refresh_theme(self): self._apply_style(); self.update()
    def refresh_accent(self): self._apply_style(); self.update()

    # ── Paint ──

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        is_light = current_theme_mode() == "light"

        # Glass background — render to opaque pixmap first to avoid edge artifacts
        cache_key = (w, h, is_light)
        if not hasattr(self, '_bg_cache') or self._bg_cache[0] != cache_key:
            tmp = QPixmap(w, h)
            tmp.fill(Qt.GlobalColor.transparent)
            pp = QPainter(tmp)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bg = QColor(30, 30, 30, 210) if not is_light else QColor(255, 255, 255, 210)
            pp.setPen(Qt.PenStyle.NoPen)
            pp.setBrush(bg)
            pp.drawRoundedRect(0, 0, w, h, 16, 16)
            pp.end()
            self._bg_cache = (cache_key, tmp)
        p.drawPixmap(0, 0, self._bg_cache[1])

        # Progress indicator (ring includes its own border, line doesn't)
        from PyQt6.QtCore import QSettings
        style = str(QSettings("VBPlayer", "VB Player").value("pill_progress_style", "line") or "line")
        if style == "ring":
            self._draw_ring_progress(p, w, h)
        else:
            # Subtle border + top line
            p.setPen(QColor(255, 255, 255, 25) if not is_light else QColor(0, 0, 0, 25))
            p.drawPath(path)
            self._draw_line_progress(p, w, h, is_light)

        p.end()

    def _draw_line_progress(self, p, w, h, is_light):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 30) if not is_light else QColor(0, 0, 0, 10))
        p.drawRoundedRect(8, 0, w - 16, 4, 2, 2)
        if self._ratio > 0:
            p.setBrush(current_accent())
            p.drawRoundedRect(8, 0, int((w - 16) * self._ratio), 4, 2, 2)

    def _draw_ring_progress(self, p, w, h):
        from PyQt6.QtGui import QPen
        pen_w = 2
        rx, ry = 1, 1
        rww, rhh = w - 2, h - 2
        rrad = 15

        if self._ratio <= 0:
            return

        perimeter = 2 * (rww + rhh) - (8 - 2 * 3.14159) * rrad
        progress_px = perimeter * min(self._ratio, 1.0)
        dash_on = progress_px / pen_w
        dash_off = (perimeter - progress_px + 0.1) / pen_w

        pen = QPen(current_accent(), pen_w)
        pen.setDashPattern([dash_on, dash_off])
        pen.setDashOffset(rrad / pen_w)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rx, ry, rww, rhh, rrad, rrad)

    def mouseReleaseEvent(self, e: QMouseEvent):
        child = self.childAt(e.pos())
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseReleaseEvent(e)
