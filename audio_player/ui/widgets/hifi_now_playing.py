"""HiFi Now Playing — immersive full-page playback dashboard."""

import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QMenu
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QPoint,
    QSize, QSettings, QAbstractAnimation, pyqtProperty, QObject
)
from PyQt6.QtGui import (
    QPainter, QColor, QPixmap, QFont, QLinearGradient, QPainterPath,
    QBrush, QPen, QFontMetrics, QImage, QGuiApplication, QAction
)

from audio_player.app import current_accent
from audio_player.player.audio_analyzer import LyricsLine
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT,
    NAV_SONGS, _icon,
)
from audio_player.ui.utils import format_duration, format_size


class _OpacityHelper(QObject):
    """Helper object for QPropertyAnimation on opacity."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = 1.0

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float):
        self._opacity = max(0.0, min(1.0, value))

    opacity = pyqtProperty(float, fget=get_opacity, fset=set_opacity)


# format_duration, format_size — imported from audio_player.ui.utils


def _blur_pixmap(pix: QPixmap, radius: int = 40) -> QPixmap:
    """Stack blur for background — fast enough for single image."""
    if pix.isNull():
        return pix
    # Scale down first for speed
    small = pix.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    # Use QGraphicsBlurEffect via QImage conv — simple box blur
    img = small.toImage()
    w, h = img.width(), img.height()
    # Multi-pass box blur (approximates gaussian)
    for _ in range(3):
        # Horizontal pass
        for y in range(h):
            row = []
            for x in range(w):
                row.append(img.pixelColor(x, y))
            for x in range(w):
                r = g = b = cnt = 0
                for dx in range(-radius // 4, radius // 4 + 1):
                    nx = min(max(x + dx, 0), w - 1)
                    c = row[nx]
                    r += c.red()
                    g += c.green()
                    b += c.blue()
                    cnt += 1
                img.setPixelColor(x, y, QColor(r // cnt, g // cnt, b // cnt))
        # Vertical pass
        for x in range(w):
            col = []
            for y in range(h):
                col.append(img.pixelColor(x, y))
            for y in range(h):
                r = g = b = cnt = 0
                for dy in range(-radius // 4, radius // 4 + 1):
                    ny = min(max(y + dy, 0), h - 1)
                    c = col[ny]
                    r += c.red()
                    g += c.green()
                    b += c.blue()
                    cnt += 1
                img.setPixelColor(x, y, QColor(r // cnt, g // cnt, b // cnt))
    result = QPixmap.fromImage(img)
    return result.scaled(pix.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


class HiFiNowPlayingPage(QWidget):
    """Immersive full-page HiFi playback dashboard."""

    collapseRequested = pyqtSignal()
    fullscreenRequested = pyqtSignal()
    lyricsToggled = pyqtSignal(bool)
    outputDetailRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hifiNowPlaying")
        self._cover_pixmap: QPixmap | None = None
        self._blurred_bg: QPixmap | None = None
        self._cached_bg: QPixmap | None = None  # scaled-to-window cached bg
        self._old_cached_bg: QPixmap | None = None  # previous bg during crossfade
        self._bg_fade_progress: float = 1.0  # 0=old, 1=new
        self._bg_fade_helper: _OpacityHelper | None = None
        self._macos_vibrancy = False  # True on macOS: use NSVisualEffectView instead of blur
        self._macos_vibrancy_view = None
        self._bg_fade_anim: QPropertyAnimation | None = None
        self._title = ""
        self._artist = ""
        self._album = ""
        self._quality_text = ""
        self._hovered_quality = False
        self._position_ms = 0
        self._duration_ms = 0
        self._is_playing = False
        self._accent = current_accent()

        # Lyrics state
        self._lyrics: list[LyricsLine] = []
        self._lyrics_mode = False
        self._lyrics_layout_progress = 0.0  # 0.0=Artwork, 1.0=Lyrics
        self._lyrics_active_idx = -1
        self._lyrics_anim_line = 0.0  # float for sub-pixel scroll
        self._lyrics_anim_start = 0.0
        self._lyrics_anim_target = 0.0
        self._lyrics_anim_elapsed = 0
        self._lyrics_anim_duration = 380  # ms — smoother transition
        self._lyrics_scale = 1.0  # current line scale (0.96→1.0)
        self._lyrics_scale_anim_elapsed = 0

        self._lyrics_layout_helper = _OpacityHelper(self)
        self._lyrics_layout_helper.opacity = 0.0
        self._lyrics_layout_anim: QPropertyAnimation | None = None

        self._lyrics_scroll_timer = QTimer(self)
        self._lyrics_scroll_timer.setInterval(33)  # ~30fps — smooth enough, less CPU
        self._lyrics_scroll_timer.timeout.connect(self._tick_lyrics_scroll)

        # Hover delay timer
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(600)
        self._hover_timer.timeout.connect(self._on_hover_timeout)
        self._pending_hover = False

        # Auto-hide transport buttons
        s = QSettings("VBPlayer", "VB Player")
        self._auto_hide_enabled = str(s.value("hifi_auto_hide", "true")).lower() == "true"
        self._auto_hide_seconds = int(s.value("hifi_auto_hide_seconds", 3) or 3)
        self._buttons_visible = True
        self._buttons_opacity = 1.0  # 0.0 ~ 1.0

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self._auto_hide_seconds * 1000)
        self._hide_timer.timeout.connect(self._start_hide_buttons)

        self._opacity_helper = _OpacityHelper(self)
        self._opacity_helper.opacity = 1.0
        self._fade_anim: QPropertyAnimation | None = None

        # Progress bar drag state
        self._dragging = False

        # Top-right buttons auto-hide
        self._topbar_opacity = 1.0
        self._topbar_visible = True
        self._topbar_opacity_helper = _OpacityHelper(self)
        self._topbar_opacity_helper.opacity = 1.0
        self._topbar_fade_anim: QPropertyAnimation | None = None

        self._topbar_hide_timer = QTimer(self)
        self._topbar_hide_timer.setSingleShot(True)
        self._topbar_hide_timer.setInterval(3000)
        self._topbar_hide_timer.timeout.connect(self._start_hide_topbar)

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Top-right buttons style
        btn_style = (
            "QPushButton{background:#19ffffff;color:#aaa;border:none;"
            "border-radius:18px;font-size:16px;}"
            "QPushButton:hover{background:#33ffffff;color:#fff;}"
        )

        # Lyrics button (ghost style)
        self._lyrics_btn = QPushButton("♪", self)
        self._lyrics_btn.setFixedSize(36, 36)
        self._lyrics_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lyrics_btn.setToolTip("歌词")
        self._lyrics_btn.clicked.connect(self.toggle_lyrics)
        self._lyrics_btn.setStyleSheet(btn_style)

        # Fullscreen button
        self._fullscreen_btn = QPushButton("⛶", self)
        self._fullscreen_btn.setFixedSize(36, 36)
        self._fullscreen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fullscreen_btn.setToolTip("全屏")
        self._fullscreen_btn.clicked.connect(self.fullscreenRequested)
        self._fullscreen_btn.setStyleSheet(btn_style)

        # Close button
        self._close_btn = QPushButton("✕", self)
        self._close_btn.setFixedSize(36, 36)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("收起")
        self._close_btn.clicked.connect(self.collapseRequested)
        self._close_btn.setStyleSheet(btn_style)

    # ---- Public API ----

    def set_cover(self, data: bytes | None):
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                # Save old background for crossfade
                if self._cached_bg and not self._cached_bg.isNull():
                    self._old_cached_bg = self._cached_bg
                else:
                    self._old_cached_bg = None
                self._cover_pixmap = pix
                self._blurred_bg = None  # invalidate
                self._cached_bg = None
                self._start_bg_crossfade()
                return
        self._cover_pixmap = None
        self._blurred_bg = None
        self._old_cached_bg = self._cached_bg  # fade old to empty
        self._start_bg_crossfade()

    def _start_bg_crossfade(self):
        if self._bg_fade_helper is None:
            self._bg_fade_helper = _OpacityHelper(self)
            self._bg_fade_helper._opacity = 0.0
        if self._bg_fade_anim and self._bg_fade_anim.state() == QAbstractAnimation.State.Running:
            self._bg_fade_anim.stop()
        self._bg_fade_progress = 0.0
        self._bg_fade_anim = QPropertyAnimation(self._bg_fade_helper, b"opacity")
        self._bg_fade_anim.setDuration(500)
        self._bg_fade_anim.setStartValue(0.0)
        self._bg_fade_anim.setEndValue(1.0)
        self._bg_fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._bg_fade_anim.valueChanged.connect(self._on_bg_fade_tick)
        self._bg_fade_anim.start()

    def _on_bg_fade_tick(self):
        self._bg_fade_progress = self._bg_fade_helper._opacity
        self.update()

    def set_track_info(self, title: str, artist: str, album: str):
        self._title = title or "未知曲目"
        self._artist = artist or ""
        self._album = album or ""
        self.update()

    def set_quality(self, text: str):
        self._quality_text = text
        self.update()

    def refresh_accent(self):
        self._accent = current_accent()
        self.update()

    def set_position(self, ms: int):
        self._position_ms = ms
        # Partial update: only the progress bar area (bottom ~180px)
        w = self.width()
        h = self.height()
        self.update(QRectF(0, h - 180, w, 180).toRect())

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self.update()

    def set_playing(self, playing: bool):
        self._is_playing = playing
        self.update()

    # ---- Lyrics ----

    def set_lyrics(self, lines: list):
        self._lyrics = lines if lines else []
        self._lyrics_active_idx = -1
        self._lyrics_anim_line = 0.0
        self.update()

    def set_lyrics_visible(self, visible: bool):
        if visible == self._lyrics_mode:
            return
        self._lyrics_mode = visible
        # Update lyrics button style (was in paintEvent — now once only)
        if visible:
            accent = self._accent
            self._lyrics_btn.setStyleSheet(
                f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
                f"border-radius:18px;font-size:16px;}}"
                f"QPushButton:hover{{background:{accent.lighter(120).name()};}}"
            )
        else:
            self._lyrics_btn.setStyleSheet(
                "QPushButton{background:#19ffffff;color:#aaa;border:none;"
                "border-radius:18px;font-size:16px;}"
                "QPushButton:hover{background:#33ffffff;color:#fff;}"
            )
        target = 1.0 if visible else 0.0
        # Animate layout morph
        if self._lyrics_layout_anim and self._lyrics_layout_anim.state() == QAbstractAnimation.State.Running:
            self._lyrics_layout_anim.stop()
        self._lyrics_layout_helper.opacity = self._lyrics_layout_progress
        self._lyrics_layout_anim = QPropertyAnimation(self._lyrics_layout_helper, b"opacity")
        self._lyrics_layout_anim.setDuration(400)
        self._lyrics_layout_anim.setStartValue(self._lyrics_layout_progress)
        self._lyrics_layout_anim.setEndValue(target)
        self._lyrics_layout_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._lyrics_layout_anim.valueChanged.connect(self._on_layout_progress_changed)
        self._lyrics_layout_anim.start()
        self.lyricsToggled.emit(visible)

    def _on_layout_progress_changed(self):
        self._lyrics_layout_progress = self._lyrics_layout_helper.opacity
        self.update()

    def set_lyrics_position(self, ms: int):
        if not self._lyrics:
            return
        # Find active line
        new_idx = -1
        for i, line in enumerate(self._lyrics):
            if line.time_ms <= ms:
                new_idx = i
            else:
                break
        if new_idx != self._lyrics_active_idx:
            old_idx = self._lyrics_active_idx
            self._lyrics_active_idx = new_idx
            if old_idx < 0 or abs(new_idx - old_idx) > 10:
                # Large gap (seek): jump instantly
                self._lyrics_anim_line = float(new_idx)
            else:
                # Normal playback: animate
                self._lyrics_anim_start = self._lyrics_anim_line
                self._lyrics_anim_target = float(new_idx)
                self._lyrics_anim_elapsed = 0
                self._lyrics_scroll_timer.start()
                # Trigger scale animation for current line
                self._lyrics_scale = 0.96
                self._lyrics_scale_anim_elapsed = 0
        if self._lyrics_mode and self._lyrics_layout_progress > 0.01:
            self.update()

    def _tick_lyrics_scroll(self):
        self._lyrics_anim_elapsed += 33
        self._lyrics_scale_anim_elapsed += 33
        t = min(1.0, self._lyrics_anim_elapsed / self._lyrics_anim_duration)
        ease = 1.0 - (1.0 - t) ** 3
        self._lyrics_anim_line = self._lyrics_anim_start + (self._lyrics_anim_target - self._lyrics_anim_start) * ease
        # Scale animation: 0.96 → 1.0
        scale_t = min(1.0, self._lyrics_scale_anim_elapsed / 150)
        self._lyrics_scale = 0.96 + 0.04 * (1.0 - (1.0 - scale_t) ** 3)
        if t >= 1.0:
            self._lyrics_scroll_timer.stop()
            self._lyrics_scale = 1.0
        # Only redraw lyrics area, not the entire widget
        w = self.width()
        lyrics_rect = QRectF(w * 0.35, 0, w * 0.6, self.height())
        self.update(lyrics_rect.toRect())

    def toggle_lyrics(self):
        self.set_lyrics_visible(not self._lyrics_mode)

    # ---- Auto-hide transport buttons ----

    def _buttons_zone_rect(self) -> QRectF:
        """Rect where mouse presence keeps buttons visible (above progress bar)."""
        w, h = self.width(), self.height()
        side_size = 56
        play_size = 72
        groove_h = 12
        bottom_margin = 60
        btn_center_y = h - bottom_margin - play_size / 2
        bar_y = btn_center_y - play_size / 2 - 24 - groove_h
        # Quality info is above progress bar
        quality_y = bar_y - 44
        return QRectF(0, quality_y, w, h - quality_y)

    def _start_hide_buttons(self):
        """Start fade-out animation for transport buttons."""
        if not self._auto_hide_enabled or not self._buttons_visible:
            return
        self._animate_buttons(1.0, 0.0, 150)

    def _show_buttons(self):
        """Start fade-in animation for transport buttons."""
        if self._buttons_visible and self._buttons_opacity > 0.9:
            return
        self._hide_timer.stop()
        self._animate_buttons(self._buttons_opacity, 1.0, 150)
        if self._auto_hide_enabled:
            self._hide_timer.start()

    def _animate_buttons(self, start: float, end: float, duration: int):
        """Instantly set buttons opacity — no animation to avoid paintEvent spam."""
        self._opacity_helper.opacity = end
        self._buttons_opacity = end
        self._buttons_visible = end > 0.5
        btn_y = self.height() - 140
        self.update(QRectF(0, btn_y - 20, self.width(), 160).toRect())

    def _on_opacity_changed(self):
        """Called during fade animation to update opacity and repaint."""
        self._buttons_opacity = self._opacity_helper.opacity
        self.update()

    def _on_fade_finished(self):
        if self._buttons_opacity < 0.1:
            self._buttons_visible = False
        else:
            self._buttons_visible = True

    def _reset_hide_timer(self):
        """Reset the auto-hide timer (called on mouse move in button zone)."""
        if self._auto_hide_enabled:
            self._hide_timer.stop()
            self._hide_timer.start()

    def _show_auto_hide_menu(self, pos: QPoint):
        """Show right-click context menu."""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1a1a2e;color:#e2e8f0;border:1px solid #2a2a4a;"
            "border-radius:6px;padding:4px;}"
            "QMenu::item{padding:6px 16px;border-radius:4px;}"
            "QMenu::item:selected{background:#2a2a4a;}"
            "QMenu::separator{height:1px;background:#2a2a4a;margin:4px 8px;}"
        )

        # Lyrics toggle
        lyrics_action = QAction("♪ 歌词", menu)
        lyrics_action.setCheckable(True)
        lyrics_action.setChecked(self._lyrics_mode)
        lyrics_action.triggered.connect(self.toggle_lyrics)
        menu.addAction(lyrics_action)

        menu.addSeparator()

        # Toggle auto-hide
        hide_action = QAction("自动隐藏", menu)
        hide_action.setCheckable(True)
        hide_action.setChecked(self._auto_hide_enabled)
        hide_action.triggered.connect(self._toggle_auto_hide)
        menu.addAction(hide_action)

        menu.addSeparator()

        # Seconds options
        for secs in [3, 5, 8, 10]:
            act = QAction(f"{secs} 秒", menu)
            act.setCheckable(True)
            act.setChecked(self._auto_hide_seconds == secs)
            act.triggered.connect(lambda checked, s=secs: self._set_auto_hide_seconds(s))
            menu.addAction(act)

        menu.exec(pos)

    def _toggle_auto_hide(self, checked: bool):
        self._auto_hide_enabled = checked
        QSettings("VBPlayer", "VB Player").setValue("hifi_auto_hide", checked)
        if checked:
            self._reset_hide_timer()
        else:
            self._hide_timer.stop()
            if not self._buttons_visible:
                self._show_buttons()

    def _set_auto_hide_seconds(self, secs: int):
        self._auto_hide_seconds = secs
        self._hide_timer.setInterval(secs * 1000)
        QSettings("VBPlayer", "VB Player").setValue("hifi_auto_hide_seconds", secs)

    # ---- Auto-hide top-right buttons ----

    def _topbar_zone_rect(self) -> QRectF:
        """Rect near top-right corner that keeps topbar visible."""
        w = self.width()
        return QRectF(w - 200, 0, 200, 70)

    def _start_hide_topbar(self):
        if not self._topbar_visible:
            return
        self._animate_topbar(1.0, 0.0, 150)

    def _show_topbar(self):
        if self._topbar_visible and self._topbar_opacity > 0.9:
            return
        self._topbar_hide_timer.stop()
        self._animate_topbar(self._topbar_opacity, 1.0, 150)
        self._topbar_hide_timer.start()

    def _animate_topbar(self, start: float, end: float, duration: int):
        """Instant topbar show/hide — no animation to avoid CPU waste."""
        self._topbar_opacity_helper.opacity = end
        self._topbar_opacity = end
        self._topbar_visible = end > 0.1
        self._on_topbar_opacity_changed()

    def _on_topbar_opacity_changed(self):
        self._topbar_opacity = self._topbar_opacity_helper.opacity
        # Close button always visible — user must be able to exit
        if self._topbar_opacity < 0.1:
            self._fullscreen_btn.hide()
            self._lyrics_btn.hide()
        else:
            self._fullscreen_btn.show()
            self._lyrics_btn.show()
        self._close_btn.show()  # always
        self.update()

    def _on_topbar_fade_finished(self):
        self._topbar_visible = self._topbar_opacity > 0.1

    # ---- Events ----

    def showEvent(self, e):
        super().showEvent(e)
        # Start auto-hide timers when page becomes visible
        self._buttons_visible = True
        self._buttons_opacity = 1.0
        self._topbar_visible = True
        self._topbar_opacity = 1.0
        self._close_btn.show()  # always visible — exit must be reachable
        if self._auto_hide_enabled:
            self._hide_timer.start()
            self._topbar_hide_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        # Stop timers when page is hidden
        self._hide_timer.stop()
        self._topbar_hide_timer.stop()
        if self._fade_anim and self._fade_anim.state() == QAbstractAnimation.State.Running:
            self._fade_anim.stop()
        if self._topbar_fade_anim and self._topbar_fade_anim.state() == QAbstractAnimation.State.Running:
            self._topbar_fade_anim.stop()

    def mouseMoveEvent(self, e):
        pos = e.position()

        # Handle progress bar dragging
        if self._dragging:
            self._seek_from_mouse(pos.x())
            return

        # Check if hovering over quality area
        quality_rect = self._quality_rect()
        in_quality = quality_rect.contains(pos)
        if in_quality and not self._hovered_quality and not self._pending_hover:
            self._pending_hover = True
            self._hover_timer.start()
        elif not in_quality:
            self._hover_timer.stop()
            self._pending_hover = False
            if self._hovered_quality:
                self._hovered_quality = False
                self.update()

        # Auto-hide: show buttons when mouse in button zone, reset timer
        if self._buttons_zone_rect().contains(pos):
            if not self._buttons_visible or self._buttons_opacity < 0.9:
                self._show_buttons()
            self._reset_hide_timer()

        # Auto-hide topbar: show when mouse near top-right corner
        if self._topbar_zone_rect().contains(pos):
            if not self._topbar_visible or self._topbar_opacity < 0.9:
                self._show_topbar()
            else:
                self._topbar_hide_timer.stop()
                self._topbar_hide_timer.start()
        super().mouseMoveEvent(e)

    def contextMenuEvent(self, e):
        self._show_auto_hide_menu(e.globalPos())

    def _on_hover_timeout(self):
        self._pending_hover = False
        self._hovered_quality = True
        self.update()

    def _controls_rect(self) -> QRectF:
        """Return the general controls area for click detection."""
        w, h = self.width(), self.height()
        cx = w / 2
        progress = self._lyrics_layout_progress
        side_size = int(56 + (40 - 56) * progress)
        play_size = int(72 + (52 - 72) * progress)
        btn_spacing = int(80 + (56 - 80) * progress)
        bottom_margin = int(60 + (40 - 60) * progress)
        cover_size_artwork = min(int(h * 0.38), int(w * 0.35), 380)
        cover_size_lyrics = min(int(h * 0.22), int(w * 0.18), 240)
        cover_size = int(cover_size_artwork + (cover_size_lyrics - cover_size_artwork) * progress)
        cover_x_artwork = (w - cover_size) / 2
        cover_x_lyrics = w * 0.08
        cover_x = cover_x_artwork + (cover_x_lyrics - cover_x_artwork) * progress
        controls_cx = cx + (cover_x + cover_size / 2 - cx) * progress
        controls_cx = max(btn_spacing + side_size, min(w - btn_spacing - side_size, controls_cx))
        btn_center_y = h - bottom_margin - play_size / 2
        side_y = btn_center_y - side_size / 2
        play_y = btn_center_y - play_size / 2
        return controls_cx, side_size, play_size, btn_spacing, side_y, play_y

    def _button_at(self, pos) -> str | None:
        """Check if position is on a transport button. Returns 'prev', 'play', 'next', or None."""
        controls_cx, side_size, play_size, btn_spacing, side_y, play_y = self._controls_rect()
        if QRectF(controls_cx - btn_spacing - side_size / 2, side_y, side_size, side_size).contains(pos):
            return "prev"
        if QRectF(controls_cx - play_size / 2, play_y, play_size, play_size).contains(pos):
            return "play"
        if QRectF(controls_cx + btn_spacing - side_size / 2, side_y, side_size, side_size).contains(pos):
            return "next"
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position()
            btn = self._button_at(pos)
            if btn == "play":
                self._on_toggle()
                return
            elif btn == "prev":
                self._on_prev()
                return
            elif btn == "next":
                self._on_next()
                return
            if self._quality_rect().contains(pos):
                self.outputDetailRequested.emit()
                return
            if self._duration_ms > 0 and self._progress_bar_rect().contains(pos):
                self._dragging = True
                self._seek_from_mouse(pos.x())
                return
        super().mousePressEvent(e)

    def _quality_rect(self) -> QRectF:
        w, h = self.width(), self.height()
        cx = w / 2
        side_size = 56
        play_size = 72
        groove_h = 12
        bottom_margin = 60
        btn_center_y = h - bottom_margin - play_size / 2
        bar_y = btn_center_y - play_size / 2 - 24 - groove_h
        qy = bar_y - 28
        return QRectF(cx - 200, qy - 10, 400, 40)

    def _progress_bar_rect(self) -> QRectF:
        """Return the clickable area of the progress bar (generous hit area)."""
        w, h = self.width(), self.height()
        cx = w / 2
        groove_h = 12
        progress = self._lyrics_layout_progress

        # Same interpolated values as paintEvent
        cover_size_artwork = min(int(h * 0.38), int(w * 0.35), 380)
        cover_size_lyrics = min(int(h * 0.22), int(w * 0.18), 240)
        cover_size = int(cover_size_artwork + (cover_size_lyrics - cover_size_artwork) * progress)
        cover_x_artwork = (w - cover_size) / 2
        cover_x_lyrics = w * 0.08
        cover_x = cover_x_artwork + (cover_x_lyrics - cover_x_artwork) * progress
        controls_cx = cx + (cover_x + cover_size / 2 - cx) * progress
        controls_cx = max(80, min(w - 80, controls_cx))

        play_size = int(72 + (52 - 72) * progress)
        bottom_margin = int(60 + (40 - 60) * progress)
        bar_w_artwork = min(500, int(w * 0.5))
        bar_w_lyrics = cover_size
        bar_w = int(bar_w_artwork + (bar_w_lyrics - bar_w_artwork) * progress)
        bar_x = max(20, min(controls_cx - bar_w / 2, w - bar_w - 20))
        btn_center_y = h - bottom_margin - play_size / 2
        bar_y = btn_center_y - play_size / 2 - 24 - groove_h
        # Generous hit area
        return QRectF(bar_x - 10, bar_y - 10, bar_w + 20, groove_h + 20)

    def _seek_from_mouse(self, x: float):
        """Seek to position based on mouse x coordinate."""
        w, h = self.width(), self.height()
        cx = w / 2
        progress = self._lyrics_layout_progress

        # Same interpolated values as paintEvent
        cover_size_artwork = min(int(h * 0.38), int(w * 0.35), 380)
        cover_size_lyrics = min(int(h * 0.22), int(w * 0.18), 240)
        cover_size = int(cover_size_artwork + (cover_size_lyrics - cover_size_artwork) * progress)
        cover_x_artwork = (w - cover_size) / 2
        cover_x_lyrics = w * 0.08
        cover_x = cover_x_artwork + (cover_x_lyrics - cover_x_artwork) * progress
        controls_cx = cx + (cover_x + cover_size / 2 - cx) * progress
        controls_cx = max(80, min(w - 80, controls_cx))

        bar_w_artwork = min(500, int(w * 0.5))
        bar_w_lyrics = cover_size
        bar_w = int(bar_w_artwork + (bar_w_lyrics - bar_w_artwork) * progress)
        bar_x = max(20, min(controls_cx - bar_w / 2, w - bar_w - 20))

        ratio = (x - bar_x) / bar_w
        ratio = max(0.0, min(1.0, ratio))
        self.seekRequested.emit(int(ratio * self._duration_ms))

    # ---- Painting ----

    def paintEvent(self, event):
        p = QPainter(self)
        # macOS vibrancy: apply once after first show
        if sys.platform == "darwin" and not self._macos_vibrancy and self.isVisible() and self.width() > 0:
            self._macos_vibrancy = True
            try:
                from audio_player.platform.macos.materials import enable_vibrancy
                self._macos_vibrancy_view = enable_vibrancy(self, material="hudWindow")
            except Exception:
                self._macos_vibrancy = False  # fall back to software blur
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()

        # ---- Background: blurred cover with crossfade ----
        if self._cover_pixmap and not self._cover_pixmap.isNull():
            if self._blurred_bg is None or not self._macos_vibrancy:
                self._blurred_bg = _blur_pixmap(self._cover_pixmap)
            if self._cached_bg is None or self._cached_bg.size() != self.size():
                self._cached_bg = self._blurred_bg.scaled(
                    w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)

            t = self._bg_fade_progress
            # Draw old background (fading out) if crossfade in progress
            if t < 1.0 and self._old_cached_bg and not self._old_cached_bg.isNull():
                old_scaled = self._old_cached_bg.scaled(w, h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                p.setOpacity(1.0 - t)
                p.drawPixmap(0, 0, old_scaled)
                p.setOpacity(1.0)
            # Draw new background
            if t > 0:
                p.setOpacity(t)
                p.drawPixmap(0, 0, self._cached_bg)
                p.setOpacity(1.0)
            # Dark overlay on top
            p.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))
        else:
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0.0, QColor("#0d0d1a"))
            grad.setColorAt(1.0, QColor("#1a1a2e"))
            p.fillRect(0, 0, w, h, grad)

        # ---- Top-right buttons position ----
        self._close_btn.move(w - 50, 16)
        self._fullscreen_btn.move(w - 94, 16)
        self._lyrics_btn.move(w - 138, 16)

        # ---- Layout morph interpolation ----
        progress = self._lyrics_layout_progress  # 0.0=Artwork, 1.0=Lyrics
        cx = w / 2

        # Cover size: Artwork 380 → Lyrics smaller
        cover_size_artwork = min(int(h * 0.38), int(w * 0.35), 380)
        cover_size_lyrics = min(int(h * 0.22), int(w * 0.18), 240)
        cover_size = int(cover_size_artwork + (cover_size_lyrics - cover_size_artwork) * progress)

        # Cover position: Artwork centered → Lyrics upper left
        cover_x_artwork = (w - cover_size) / 2
        cover_x_lyrics = w * 0.08
        cover_x = cover_x_artwork + (cover_x_lyrics - cover_x_artwork) * progress

        cover_y_artwork = h * 0.15
        cover_y_lyrics = h * 0.08
        cover_y = cover_y_artwork + (cover_y_lyrics - cover_y_artwork) * progress

        # Shadow opacity: 80 → 30
        shadow_alpha = int(80 - 50 * progress)

        # Metadata opacity: 1.0 → 0.55 (eased)
        meta_ease = 1.0 - (1.0 - progress) ** 2 * 0.45

        # Progress/controls opacity: 1.0 → 0.65/0.85
        progress_opacity = 1.0 - progress * 0.35
        controls_opacity = 1.0 - progress * 0.15

        # ---- Layer 1: Cover art ----
        if self._cover_pixmap and not self._cover_pixmap.isNull():
            # Shadow
            shadow = QPainterPath()
            shadow.addRoundedRect(QRectF(cover_x + 3, cover_y + 5,
                                         cover_size, cover_size), 12, 12)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, shadow_alpha))
            p.drawPath(shadow)

            # Cover with rounded corners
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(cover_x, cover_y,
                                       cover_size, cover_size), 12, 12)
            p.setClipPath(clip)

                        # Cache scaled cover - SmoothTransformation is expensive
            _cache_key = (cover_size, id(self._cover_pixmap))
            if getattr(self, '_cached_cover_key', None) != _cache_key:
                self._cached_cover_key = _cache_key
                self._cached_cover_scaled = self._cover_pixmap.scaled(
                    cover_size, cover_size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
            scaled = self._cached_cover_scaled
            src_x = (scaled.width() - cover_size) / 2
            src_y = (scaled.height() - cover_size) / 2
            p.drawPixmap(int(cover_x), int(cover_y), scaled,
                         int(src_x), int(src_y), cover_size, cover_size)
            p.setClipping(False)

            # Subtle border
            p.setPen(QPen(QColor(255, 255, 255, 20), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(cover_x, cover_y,
                                     cover_size, cover_size), 12, 12)
        else:
            # Placeholder
            rect = QRectF(cover_x, cover_y, cover_size, cover_size)
            grad = QLinearGradient(cover_x, cover_y,
                                   cover_x + cover_size, cover_y + cover_size)
            grad.setColorAt(0.0, QColor("#1e1e40"))
            grad.setColorAt(1.0, QColor("#2d1b69"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(rect, 12, 12)
            font = QFont()
            font.setPointSize(cover_size // 4)
            p.setFont(font)
            p.setPen(QColor("#a78bfa"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "♪")

        # ---- Layer 1: Track info (with metadata opacity) ----
        p.setOpacity(meta_ease)
        text_y = cover_y + cover_size + 32

        # Alignment: centered in Artwork, left-aligned in Lyrics
        if progress > 0.5:
            text_align = Qt.AlignmentFlag.AlignLeft
            text_x = cover_x
            text_w = cover_size
        else:
            text_align = Qt.AlignmentFlag.AlignHCenter
            text_x = cx - 250
            text_w = 500

        # Title
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor("#ffffff"))
        title_h = 36
        title_rect = QRectF(text_x, text_y, text_w, title_h)
        fm = QFontMetrics(title_font)
        elided = fm.elidedText(self._title, Qt.TextElideMode.ElideRight, text_w - 10)
        p.drawText(title_rect, text_align | Qt.AlignmentFlag.AlignVCenter, elided)
        text_y += title_h + 8

        # Artist
        artist_font = QFont()
        artist_font.setPointSize(14)
        p.setFont(artist_font)
        p.setPen(QColor(self._accent.lighter(130).name()))
        artist_h = 24
        artist_rect = QRectF(text_x, text_y, text_w, artist_h)
        fm2 = QFontMetrics(artist_font)
        elided2 = fm2.elidedText(self._artist, Qt.TextElideMode.ElideRight, text_w - 10)
        p.drawText(artist_rect, text_align | Qt.AlignmentFlag.AlignVCenter, elided2)
        text_y += artist_h + 4

        # Album
        album_font = QFont()
        album_font.setPointSize(11)
        p.setFont(album_font)
        p.setPen(QColor("#8899aa"))
        album_h = 20
        album_rect = QRectF(text_x, text_y, text_w, album_h)
        fm3 = QFontMetrics(album_font)
        elided3 = fm3.elidedText(self._album, Qt.TextElideMode.ElideRight, text_w - 10)
        p.drawText(album_rect, text_align | Qt.AlignmentFlag.AlignVCenter, elided3)
        text_y += album_h
        p.setOpacity(1.0)

        # ---- Layer 1.5: Lyrics (right side, visible in Lyrics mode) ----
        if progress > 0.01 and self._lyrics:
            self._paint_lyrics(p, w, h, progress)

        # ---- Layer 2+3: Progress bar + Transport buttons + Quality info ----
        # Match TransportBar sizes: play=72, side=56
        side_size_artwork = 56
        play_size_artwork = 72
        btn_spacing_artwork = 80

        side_size_lyrics = 40
        play_size_lyrics = 52
        btn_spacing_lyrics = 56

        side_size = int(side_size_artwork + (side_size_lyrics - side_size_artwork) * progress)
        play_size = int(play_size_artwork + (play_size_lyrics - play_size_artwork) * progress)
        btn_spacing = int(btn_spacing_artwork + (btn_spacing_lyrics - btn_spacing_artwork) * progress)

        groove_h = 12
        bottom_margin_artwork = 60
        bottom_margin_lyrics = 40
        bottom_margin = int(bottom_margin_artwork + (bottom_margin_lyrics - bottom_margin_artwork) * progress)

        # Layout center: Artwork centered → Lyrics upper left (aligned with cover)
        controls_cx_artwork = cx
        controls_cx_lyrics = cover_x + cover_size / 2
        controls_cx = controls_cx_artwork + (controls_cx_lyrics - controls_cx_artwork) * progress
        # Clamp to keep controls within window bounds
        controls_cx = max(btn_spacing + side_size, min(w - btn_spacing - side_size, controls_cx))

        # Transport buttons row — vertically centered on the larger play button
        btn_center_y = h - bottom_margin - play_size / 2
        side_y = btn_center_y - side_size / 2
        play_y = btn_center_y - play_size / 2

        # Progress bar position (above buttons) — lyrics mode locks to cover width
        bar_w_artwork = min(500, int(w * 0.5))
        bar_w_lyrics = cover_size
        bar_w = int(bar_w_artwork + (bar_w_lyrics - bar_w_artwork) * progress)
        bar_x = max(20, min(controls_cx - bar_w / 2, w - bar_w - 20))
        bar_y = btn_center_y - play_size / 2 - 24 - groove_h

        # Apply auto-hide + lyrics mode opacity to transport buttons
        combined_btn_opacity = self._buttons_opacity * controls_opacity
        if combined_btn_opacity > 0.01:
            p.setOpacity(combined_btn_opacity)
            # Previous
            self._draw_transport_btn(p, controls_cx - btn_spacing - side_size / 2, side_y,
                                     side_size, TRANSPORT_PREV, not self._is_playing)
            # Play/Pause
            play_icon_name = TRANSPORT_PAUSE if self._is_playing else TRANSPORT_PLAY
            self._draw_play_btn(p, controls_cx - play_size / 2, play_y, play_size, play_icon_name)
            # Next
            self._draw_transport_btn(p, controls_cx + btn_spacing - side_size / 2, side_y,
                                     side_size, TRANSPORT_NEXT, not self._is_playing)
            p.setOpacity(1.0)

        # Progress bar — with lyrics mode opacity
        if self._duration_ms > 0 and progress_opacity > 0.01:
            p.setOpacity(progress_opacity)
            ratio = self._position_ms / self._duration_ms

            # Groove background — muted accent, very subtle
            groove_r = groove_h // 2
            p.setPen(Qt.PenStyle.NoPen)
            muted_accent = QColor(self._accent)
            muted_accent.setAlpha(40)
            p.setBrush(muted_accent)
            p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, groove_h), groove_r, groove_r)

            # Played portion — full accent color
            accent_color = QColor(self._accent)
            p.setBrush(accent_color)
            fill_w = bar_w * ratio
            if fill_w > 0:
                p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, groove_h), groove_r, groove_r)

            # Time labels — muted accent, same as artist name
            if progress < 0.5:
                time_font = QFont()
                time_font.setPointSize(10)
                p.setFont(time_font)
                p.setPen(self._accent.lighter(130))
                time_y = bar_y + groove_h + 12
                p.drawText(QRectF(bar_x, time_y, 48, 16),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           format_duration(self._position_ms / 1000))
                p.drawText(QRectF(bar_x + bar_w - 48, time_y, 48, 16),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           format_duration(self._duration_ms / 1000))
            p.setOpacity(1.0)

        # ---- Layer 2: HiFi quality info (above progress bar) ----
        if self._quality_text:
            qy = bar_y - 28
            q_font = QFont()
            q_font.setPointSize(10)
            q_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
            p.setFont(q_font)

            p.setPen(QColor(self._accent.lighter(120).name()))

            # Simplified format in lyrics mode: "FLAC · 24bit · 96kHz"
            if progress > 0.5:
                parts = self._quality_text.split(" · ")
                simplified = " · ".join(parts[:2]) if len(parts) >= 2 else self._quality_text
                fm = QFontMetrics(q_font)
                text_w = fm.horizontalAdvance(simplified)
                p.drawText(int(bar_x + bar_w / 2 - text_w / 2), int(qy), simplified)
            else:
                q_rect = QRectF(controls_cx - 200, qy, 400, 20)
                p.drawText(q_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                           self._quality_text)

        p.end()

    # ---- Lyrics rendering ----

    def _paint_lyrics(self, p: QPainter, w: int, h: int, progress: float):
        """Render lyrics in the right area with scrolling and focus shifting."""
        accent = self._accent
        # Lyrics area: right side with breathing room
        lyrics_x = w * 0.42
        lyrics_w = w * 0.50

        if lyrics_w < 100:
            return

        # Visual center Y (slightly above true center)
        visual_center_y = h * 0.44

        # Font size: dynamic based on window width
        base_font_size = max(28, min(40, int(w * 0.022)))

        # Soft fade masks at top and bottom
        fade_h = int(h * 0.12)

        p.setOpacity(progress)

        n = len(self._lyrics)
        half_visible = 5

        for i in range(max(0, self._lyrics_active_idx - half_visible),
                       min(n, self._lyrics_active_idx + half_visible + 1)):
            line = self._lyrics[i]
            dist = i - self._lyrics_anim_line  # float for sub-pixel

            abs_dist = abs(dist)
            if abs_dist > half_visible + 1:
                continue

            # Current line
            if abs_dist < 0.5:
                # Scale animation
                font_size = int(base_font_size * self._lyrics_scale)
                font = QFont()
                font.setPointSize(font_size)
                font.setBold(True)
                p.setFont(font)
                # Color: accent with scale-linked opacity
                line_opacity = 0.75 + 0.25 * self._lyrics_scale
                color = QColor(accent)
                color.setAlphaF(line_opacity)
                p.setPen(color)

                y = int(visual_center_y)
                # Draw text at point — no rect clipping
                p.drawText(int(lyrics_x), y, line.text)

                # Translation (below current line, same visual unit)
                if line.translation:
                    t_font = QFont()
                    t_font.setPointSize(max(14, base_font_size - 6))
                    p.setFont(t_font)
                    t_color = QColor(accent)
                    t_color.setAlphaF(0.55)
                    p.setPen(t_color)
                    p.drawText(int(lyrics_x), y + 52, line.translation)

            else:
                # Non-current lines: fade + shrink with distance
                fade = max(0.0, 1.0 - abs_dist / (half_visible + 1) * 0.85)
                font_size = max(14, base_font_size - int(abs_dist * 3))
                font = QFont()
                font.setPointSize(font_size)
                p.setFont(font)

                color = QColor("#8899aa")
                color.setAlphaF(fade * 0.7)
                p.setPen(color)

                # Y offset from center (sub-pixel) — generous spacing
                line_height = int(base_font_size * 3.0)
                y_offset = dist * line_height
                # Add extra space for translation lines
                if (i > 0 and i <= self._lyrics_active_idx and
                    self._lyrics[i - 1].translation and i - 1 == self._lyrics_active_idx):
                    y_offset += 30
                y = int(visual_center_y + y_offset)

                # Draw text at point — no rect clipping
                p.drawText(int(lyrics_x), y, line.text)

        # No lyrics message
        if not self._lyrics:
            font = QFont()
            font.setPointSize(14)
            p.setFont(font)
            color = QColor("#556677")
            color.setAlphaF(0.5)
            p.setPen(color)
            p.drawText(int(lyrics_x), int(visual_center_y), "No synced lyrics")

        p.setOpacity(1.0)

    def _draw_transport_btn(self, p: QPainter, x: float, y: float,
                            size: int, icon_name: str, dim: bool):
        # Transparent background circle (matches TransportBar style)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        radius = size * 2 // 5
        p.drawEllipse(QRectF(x, y, size, size))
        # Draw icon centered
        icon_color = "#bbbbbb" if dim else "#cccccc"
        icon = _icon(icon_name, color=icon_color)
        icon_sz = int(size * 0.42)
        icon_x = int(x + (size - icon_sz) / 2)
        icon_y = int(y + (size - icon_sz) / 2)
        icon.paint(p, icon_x, icon_y, icon_sz, icon_sz)

    def _draw_play_btn(self, p: QPainter, x: float, y: float,
                       size: int, icon_name: str):
        # Accent color circle (matches TransportBar style)
        accent = QColor(self._accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        radius = size * 2 // 5
        p.drawEllipse(QRectF(x, y, size, size))
        # Draw icon centered
        icon = _icon(icon_name, color="#ffffff")
        icon_sz = int(size * 0.45)
        icon_x = int(x + (size - icon_sz) / 2)
        icon_y = int(y + (size - icon_sz) / 2)
        icon.paint(p, icon_x, icon_y, icon_sz, icon_sz)

    # ---- Click handling for transport ----

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        # End drag — seek to final position
        if self._dragging:
            self._dragging = False
            self._seek_from_mouse(e.position().x())

    # ---- Signals for transport ----
    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    seekRequested = pyqtSignal(int)

    def _on_toggle(self):
        self.playPauseClicked.emit()

    def _on_next(self):
        self.nextClicked.emit()

    def _on_prev(self):
        self.prevClicked.emit()
