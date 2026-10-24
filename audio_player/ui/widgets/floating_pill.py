"""Floating pill — Apple Music-style centered playback capsule."""

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QGraphicsOpacityEffect)
from PyQt6.QtCore import (Qt, pyqtSignal, QPropertyAnimation, QEasingCurve,
                          QPoint, QTimer, pyqtProperty)
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QFont, QPixmap, QPainterPath, QIcon

from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _
from audio_player.ui.utils import format_duration
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon,
)

PILL_W = 580
PILL_H = 72
COVER_SIZE = 40

_IDLE_COLOR = "#999"
_BRIGHT_COLOR = "#f0f0f0"


class _FadeIconButton(QPushButton):
    """Secondary pill button: icon brightens on hover (enter/leave driven
    icon-swap — cheap, no per-frame animation)."""

    def __init__(self, icon_name: str, size: int = 36, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._bright = False
        self.setObjectName("pillBtn")
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(_icon(icon_name, color=_IDLE_COLOR))

    def _refresh_icon(self):
        self.setIcon(_icon(self._icon_name, color=_BRIGHT_COLOR if self._bright else _IDLE_COLOR))

    def enterEvent(self, event):
        self._bright = True
        self._refresh_icon()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._bright = False
        self._refresh_icon()
        super().leaveEvent(event)

    def force_idle(self):
        """Reset to the idle icon and drop any hover state — used when the
        button fades out, so the disabled-icon regeneration never flashes
        a different tint mid-fade."""
        self._bright = False
        icon = _icon(self._icon_name, color=_IDLE_COLOR)
        # pre-cache the Disabled-mode pixmap (qtawesome engines can't be
        # mutated in place; build a fresh QIcon carrying both modes)
        fixed = QIcon()
        for size in (16, 24, 32, 64):
            pm = icon.pixmap(size, size)
            fixed.addPixmap(pm, QIcon.Mode.Normal)
            fixed.addPixmap(pm, QIcon.Mode.Disabled)
        self.setIcon(fixed)

    def refresh_accent(self):
        """Re-render icon after theme change."""
        self._refresh_icon()


class FloatingPill(QWidget):
    """Centered floating playback capsule — glass background, cover, progress bar."""

    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    expandRequested = pyqtSignal()
    volumeChanged = pyqtSignal(float)   # 0.0 - 1.0, user-initiated (wheel)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("floatingPill")
        self.setFixedHeight(PILL_H)
        self.setMaximumWidth(PILL_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("pill.wheel_hint"))
        self._ratio = 0.0
        self._duration_ms = 1
        self._position_ms = 0
        self._volume = 1.0
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

        # Prev — hidden until hover (Apple Music style secondary control):
        # keeps its layout slot so nothing shifts, fades in on hover
        self._prev_btn = _FadeIconButton(TRANSPORT_PREV)
        self._prev_btn.setToolTip(_("pill.prev_hover_hint"))
        self._prev_btn.clicked.connect(self.prevClicked.emit)
        layout.addWidget(self._prev_btn)

        # Play
        self._play_btn = QPushButton()
        self._play_btn.setIcon(_icon(TRANSPORT_PLAY, color="#fff"))
        self._play_btn.setObjectName("pillPlayBtn")
        self._play_btn.setFixedSize(40, 40)
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.setToolTip(_("transport.play_pause"))
        self._play_btn.clicked.connect(self.playPauseClicked.emit)
        layout.addWidget(self._play_btn)

        # Next
        self._next_btn = _FadeIconButton(TRANSPORT_NEXT)
        self._next_btn.setToolTip(_("transport.next"))
        self._next_btn.clicked.connect(self.nextClicked.emit)
        layout.addWidget(self._next_btn)

        # Cache progress style — avoid QSettings read on every paint frame
        self._pill_progress_style = "line"

        # Secondary-control reveal (prev button) — pure opacity fade
        # (QGraphicsOpacityEffect; windowOpacity only works on top-levels)
        self._prev_effect = QGraphicsOpacityEffect(self._prev_btn)
        self._prev_btn.setGraphicsEffect(self._prev_effect)
        self._secondary_anim = QPropertyAnimation(self._prev_effect, b"opacity")
        self._secondary_anim.setDuration(220)
        self._secondary_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._set_secondary_visible(False, animate=False)

        # Volume indicator: a small bar under the pill, shown on wheel,
        # fades out after inactivity — gives the invisible wheel gesture
        # a visible anchor
        self._volume_hint_opacity = 0.0
        self._volume_hint_timer = QTimer(self)
        self._volume_hint_timer.setSingleShot(True)
        self._volume_hint_timer.timeout.connect(self._fade_volume_hint)
        self._volume_fade_anim = QPropertyAnimation(self, b"volumeHintOpacity")
        self._volume_fade_anim.setDuration(300)
        self._volume_fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # volumeHintOpacity — custom painted property for the hint bar
    def _get_volume_hint_opacity(self) -> float:
        return self._volume_hint_opacity

    def _set_volume_hint_opacity(self, v: float):
        self._volume_hint_opacity = v
        self.update()

    volumeHintOpacity = pyqtProperty(float, _get_volume_hint_opacity,
                                     _set_volume_hint_opacity)

    def _show_volume_hint(self):
        """Pop the volume bar (wheel activity) and arm the auto-fade."""
        self._volume_fade_anim.stop()
        self._volume_hint_opacity = 1.0
        self.update()
        self._volume_hint_timer.start(1200)

    def _fade_volume_hint(self):
        self._volume_fade_anim.stop()
        self._volume_fade_anim.setStartValue(self._volume_hint_opacity)
        self._volume_fade_anim.setEndValue(0.0)
        self._volume_fade_anim.start()

    def _set_secondary_visible(self, visible: bool, animate: bool = True):
        """Fade the prev button in/out. Opacity-only: layout never shifts."""
        target = 1.0 if visible else 0.0
        if not visible:
            # drop hover tint BEFORE disabling — the disabled-icon
            # regeneration would otherwise flash a different tint mid-fade
            self._prev_btn.force_idle()
        self._prev_btn.setEnabled(visible)
        if not animate:
            self._secondary_anim.stop()
            self._prev_effect.setOpacity(target)
            return
        self._secondary_anim.stop()
        self._secondary_anim.setStartValue(self._prev_effect.opacity())
        self._secondary_anim.setEndValue(target)
        self._secondary_anim.start()

    def enterEvent(self, event):
        self._set_secondary_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_secondary_visible(False)
        super().leaveEvent(event)

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
                background: {"#0f000000" if is_light else "#14ffffff"};
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
            try:
                pix = QPixmap()
                pix.loadFromData(cover_data)
            except Exception:
                self._cover_label.clear(); return
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

    def set_volume(self, vol: float, muted: bool = False):
        """Track the engine volume for wheel adjustment (no UI on the pill)."""
        self._volume = 0.0 if muted else max(0.0, min(1.0, float(vol)))

    def wheelEvent(self, event):
        """Scroll on the pill = volume ±5% (same as the full bar)."""
        dy = event.angleDelta().y()
        if dy:
            step = 0.05 if dy > 0 else -0.05
            new_vol = max(0.0, min(1.0, self._volume + step))
            self.volumeChanged.emit(new_vol)
            # show the NEW value immediately — engine echo may lag a frame
            self._volume = new_vol
            self._show_volume_hint()
        super().wheelEvent(event)

    def refresh_theme(self):
        # Re-read progress style setting in case it changed
        from PyQt6.QtCore import QSettings
        self._pill_progress_style = str(QSettings("VBPlayer", "VB Player").value(
            "pill_progress_style", "line") or "line")
        self._apply_style()
        self.update()

    def refresh_accent(self):
        self._apply_style()
        self.update()

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

        # Progress indicator
        if self._pill_progress_style == "ring":
            self._draw_ring_progress(p, w, h)
        else:
            self._draw_line_progress(p, w, h, is_light)

        # Volume hint bar (wheel activity) — centered above the bottom edge
        if self._volume_hint_opacity > 0.0:
            p.setOpacity(self._volume_hint_opacity)
            bar_w, bar_h = 64, 4
            bx, by = (w - bar_w) // 2, h - 10
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 45) if not is_light else QColor(0, 0, 0, 25))
            p.drawRoundedRect(bx, by, bar_w, bar_h, 2, 2)
            p.setBrush(current_accent())
            p.drawRoundedRect(bx, by, int(bar_w * self._volume), bar_h, 2, 2)
            p.setOpacity(1.0)

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
        pen.setDashOffset(0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rx, ry, rww, rhh, rrad, rrad)

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        """Double-click empty/cover/info areas to expand — single clicks do
        nothing (a stray click expanding to fullscreen was too aggressive)."""
        child = self.childAt(e.pos())
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseDoubleClickEvent(e)
