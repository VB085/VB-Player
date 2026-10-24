"""Floating pill — Apple Music-style centered playback capsule."""

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QGraphicsOpacityEffect)
from PyQt6.QtCore import (Qt, pyqtSignal, QPropertyAnimation, QEasingCurve,
                          QPoint, QPointF, QTimer, pyqtProperty, QRectF)
from PyQt6.QtGui import (QMouseEvent, QPainter, QColor, QFont, QPixmap,
                         QPainterPath, QIcon)

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


class MarqueeLabel(QLabel):
    """Label that scrolls overflowing text back and forth (marquee).

    Text that fits renders statically (zero timers). Overflowing text
    scrolls with a pause at each end; hovering pauses the scroll so the
    text can be read. The widget's tooltip always shows the full text.
    """

    _PAD = 24          # gap between the two passes
    _SCROLL_MS = 40    # ~25 fps
    _SPEED_PX = 0.6    # px per tick
    _EDGE_PAUSE_MS = 1200

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._offset = 0.0
        self._dir = -1
        self._overflow = False
        self._hover_paused = False
        self._edge_pause = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._SCROLL_MS)
        self._timer.timeout.connect(self._tick)

    def setText(self, text: str):  # noqa: N802 (Qt naming)
        super().setText(text)
        self.setToolTip(text)
        self._offset = 0.0
        self._dir = -1
        self._measure()

    def _measure(self):
        fm = self.fontMetrics()
        self._text_w = fm.horizontalAdvance(self.text())
        self._overflow = self._text_w > self.width() and self.width() > 0
        if self._overflow:
            if not self._timer.isActive() and not self._hover_paused:
                self._timer.start()
        else:
            self._timer.stop()
            self._offset = 0.0
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._measure()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._measure()

    def enterEvent(self, event):
        self._hover_paused = True
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_paused = False
        if self._overflow:
            self._timer.start()
        super().leaveEvent(event)

    def _tick(self):
        if self._edge_pause > 0:
            self._edge_pause -= 1
            return
        lo, hi = 0, self._text_w - self.width() + self._PAD
        self._offset += self._dir * self._SPEED_PX
        if self._offset <= -hi:
            self._offset = -hi
            self._dir = 1
            self._edge_pause = self._EDGE_PAUSE_MS // self._SCROLL_MS
        elif self._offset >= 0:
            self._offset = 0
            self._dir = -1
            self._edge_pause = self._EDGE_PAUSE_MS // self._SCROLL_MS
        self.update()

    def paintEvent(self, event):
        if not self._overflow:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        y = (self.height() + fm_ascent(self)) // 2 - 2
        p.drawText(QPoint(int(self._offset), y), self.text())
        p.end()


def fm_ascent(label: QLabel) -> int:
    return label.fontMetrics().ascent()


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
    seekRequested = pyqtSignal(int)     # ms, user-initiated (top-line scrub)

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
        self._is_playing = False
        # progress scrub state
        self._prog_hover_t = 0.0     # 0..1 eased hover thickness
        self._scrubbing = False
        self._scrub_preview_ratio = 0.0
        self._scrub_preview_ms = 0
        self.setMouseTracking(True)  # hover without buttons held

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
        self._title_label = MarqueeLabel("VB Player")
        self._title_label.setObjectName("pillTitle")
        f = QFont(); f.setPointSize(11); f.setBold(True); self._title_label.setFont(f)
        info.addWidget(self._title_label)
        self._artist_label = MarqueeLabel("")
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

        # Progress-line hover ease (thickness/bubble all interpolate from it)
        from PyQt6.QtCore import QVariantAnimation
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.valueChanged.connect(self._on_hover_anim)

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
        self._is_playing = bool(playing)
        icon = TRANSPORT_PAUSE if playing else TRANSPORT_PLAY
        self._play_btn.setIcon(_icon(icon, color="#fff"))

    def set_position(self, ms: int):
        # while scrubbing the preview drives the visuals, not the engine echo
        if not self._scrubbing:
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
        accent = current_accent()
        hover = self._prog_hover_t > 0.0
        thick = 4 + 4 * self._prog_hover_t          # 4px → 8px (eased)
        # hover darkens only slightly — 60 was read as a heavy black bar
        # line stays anchored to the pill's top edge (y=0, as before the
        # scrub interaction); thickening grows downward into the capsule
        radius = thick / 2
        # while scrubbing the preview drives the line, not the engine echo
        shown_ratio = self._scrub_preview_ratio if self._scrubbing else self._ratio

        p.setPen(Qt.PenStyle.NoPen)
        # no groove — the accent fill is the whole line
        if shown_ratio > 0:
            fill = QRectF(8, 0, (w - 16) * min(shown_ratio, 1.0), thick)
            p.setBrush(accent)
            p.drawRoundedRect(fill, radius, radius)

        # Time bubble — only while actively scrubbing (position feedback)
        if self._scrubbing:
            head_x = 8 + (w - 16) * min(shown_ratio, 1.0)
            bubble = format_duration(self._scrub_preview_ms)
            bf = QFont(self.font()); bf.setPointSize(8)
            p.setFont(bf)
            bw = p.fontMetrics().horizontalAdvance(bubble) + 14
            bh = 18
            bx = max(4, min(w - bw - 4, head_x - bw / 2))
            by = thick + 6
            bubble_rect = QRectF(bx, by, bw, bh)
            p.setBrush(QColor(20, 20, 20, 220) if not is_light else QColor(250, 250, 250, 235))
            p.drawRoundedRect(bubble_rect, 4, 4)
            p.setPen(QColor("#fff") if not is_light else QColor("#333"))
            p.drawText(bubble_rect, Qt.AlignmentFlag.AlignCenter, bubble)
            p.setPen(Qt.PenStyle.NoPen)

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
        """Double-click on cover/empty areas expands. The progress band is
        exempt: rapid scrub clicks must never expand the pill."""
        pos = e.position()
        if self._in_progress_band(pos.y()):
            e.accept()
            return
        child = self.childAt(e.pos())
        if child is None or not isinstance(child, QPushButton):
            self.expandRequested.emit()
        super().mouseDoubleClickEvent(e)

    # ── Progress scrubbing (top line) ──

    _PROG_H = 16          # hover hit-band height around the top line
    _SCRUB_MS = 16        # hover ease tick

    def _ratio_to_x(self, x: float) -> float:
        w = self.width()
        inner = max(1.0, w - 16)
        return max(0.0, min(1.0, (x - 8) / inner))

    def _in_progress_band(self, y: float) -> bool:
        return y <= self._PROG_H

    def mouseMoveEvent(self, e: QMouseEvent):
        pos = e.position()
        if self._scrubbing:
            self._scrub_preview_ratio = self._ratio_to_x(pos.x())
            self._scrub_preview_ms = int(self._scrub_preview_ratio * self._duration_ms)
            self.update()
        elif self._in_progress_band(pos.y()):
            self._start_hover()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e: QMouseEvent):
        pos = e.position()
        # single-click on the cover art expands — small target, explicit
        # intent, and tolerant of shaky hands (double-click distance limits
        # made dblclick-only expansion unreliable on a real mouse)
        if (e.button() == Qt.MouseButton.LeftButton and not self._scrubbing
                and not self._in_progress_band(pos.y())
                and self.childAt(pos) is self._cover_label):
            self.expandRequested.emit()
            e.accept()
            return
        # seeking is a playback action — only while playing
        if (e.button() == Qt.MouseButton.LeftButton
                and self._in_progress_band(pos.y()) and self._is_playing):
            self._scrubbing = True
            self._scrub_preview_ratio = self._ratio_to_x(pos.x())
            self._scrub_preview_ms = int(self._scrub_preview_ratio * self._duration_ms)
            # real-mouse drags leave the widget bounds — grab so move/release
            # keep arriving (QTest/offscreen never exposes this)
            self.grabMouse()
            e.accept()
            self.update()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._scrubbing and e.button() == Qt.MouseButton.LeftButton:
            ratio = self._ratio_to_x(e.position().x())
            self._scrubbing = False
            if self.mouseGrabber() is self:
                self.releaseMouse()
            self.seekRequested.emit(int(ratio * self._duration_ms))
            e.accept()
            self.update()
            return
        super().mouseReleaseEvent(e)

    def _start_hover(self):
        """Ease the line thicker on hover — animated 0→1 (180ms OutCubic),
        the thickness visuals all interpolate from this one value."""
        if self._prog_hover_t >= 1.0:
            return
        self._hover_anim.stop()
        self._hover_anim.setStartValue(float(self._prog_hover_t))
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._hover_anim.start()

    def _end_hover(self):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(float(self._prog_hover_t))
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.setDuration(260)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._hover_anim.start()

    def _on_hover_anim(self, v):
        self._prog_hover_t = float(v)
        self.update()

    def leaveEvent(self, event):
        if self._scrubbing:
            return  # keep the handle while the cursor stays down outside
        self._end_hover()
        self._set_secondary_visible(False)
        super().leaveEvent(event)
