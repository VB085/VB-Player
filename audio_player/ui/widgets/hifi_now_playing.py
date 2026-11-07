"""HiFi Now Playing — immersive full-page playback dashboard."""

import math
import sys

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QMenu
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QRect,
    QPoint, QPointF, QSize, QSettings, QAbstractAnimation, pyqtProperty,
    QObject, QElapsedTimer
)
from PyQt6.QtGui import (
    QPainter, QColor, QPixmap, QFont, QLinearGradient, QPainterPath,
    QBrush, QPen, QFontMetrics, QImage, QGuiApplication, QAction,
    QTextLayout, QTextOption
)

from audio_player.app import current_accent
from audio_player.player.audio_analyzer import LyricsLine
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT,
    NAV_SONGS, _icon,
)
from audio_player.ui.utils import format_duration, format_size


def _anim_running(anim) -> bool:
    """动画对象是否仍在运行。

    拆窗销毁过程中动画可能已被 C++ 侧删除而 Python 引用仍在，
    直接访问 state() 会抛 RuntimeError（曾导致关窗崩溃），统一在此防护。
    """
    try:
        return anim is not None and anim.state() == QAbstractAnimation.State.Running
    except RuntimeError:
        return False


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


def _box_blur_axis(arr: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """Moving-average along one axis with edge clamping (cumsum based)."""
    if radius <= 0:
        return arr
    a = np.moveaxis(arr, axis, 0)
    win = radius * 2 + 1
    padded = np.pad(a, ((radius, radius),) + ((0, 0),) * (a.ndim - 1),
                    mode="edge")
    c = np.cumsum(padded, axis=0, dtype=np.float32)
    c = np.concatenate([np.zeros_like(c[:1]), c], axis=0)
    out = (c[win:] - c[:-win]) / win
    return np.moveaxis(out, 0, axis)


def _blur_pixmap(pix: QPixmap, radius: int = 40) -> QPixmap:
    """Triple box blur at 80×80, vectorised with numpy.

    The old per-pixel Python version took ~100ms and ran on the first paint
    after a cover change — i.e. exactly when the immersive page opened —
    which stalled the transition's first frames.
    """
    if pix.isNull():
        return pix
    small = pix.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    img = small.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    stride = img.bytesPerLine()
    buf = np.frombuffer(img.constBits().asstring(stride * h), np.uint8)
    rgba = buf.reshape(h, stride)[:, :w * 4].reshape(h, w, 4)
    arr = rgba[:, :, :3].astype(np.float32)
    r = max(1, radius // 4)
    for _ in range(3):
        arr = _box_blur_axis(arr, r, axis=1)
        arr = _box_blur_axis(arr, r, axis=0)
    out = np.empty((h, w, 4), dtype=np.uint8)
    np.clip(arr, 0, 255, out=arr)
    out[:, :, :3] = arr.astype(np.uint8)
    out[:, :, 3] = 255
    blurred = QImage(out.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
    result = QPixmap.fromImage(blurred)
    return result.scaled(pix.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


class _LyricsLayer(QWidget):
    """Opaque lyrics surface with wrapped, cached text layouts.

    It paints its own background crop, so a 60fps scroll never re-runs the
    immersive page's background/cover painting. Text layouts cache wrapping
    and shaping; frames only move pre-laid-out blocks. Top/bottom fading is
    an alpha mask on the text layer, never a coloured bar over the backdrop.
    """

    def __init__(self, page):
        super().__init__(page)
        self._page = page
        self._font_cache: dict[tuple[int, bool], QFont] = {}
        self._layouts = []
        self._anchors: list[float] = []
        self._heights: list[float] = []
        self._layout_key = None
        self._text_layer: QPixmap | None = None
        self._bg_surface: QPixmap | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.hide()

    def lyrics_changed(self):
        self._layout_key = None
        self.update()

    def _font(self, size: int, bold: bool = False) -> QFont:
        key = (int(size), bool(bold))
        font = self._font_cache.get(key)
        if font is None:
            font = QFont()
            font.setPointSize(int(size))
            font.setBold(bool(bold))
            self._font_cache[key] = font
        return font

    @staticmethod
    def _make_layout(text: str, font: QFont, width: int) -> QTextLayout:
        layout = QTextLayout(text, font)
        layout.setCacheEnabled(True)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            line.setPosition(QPointF(0, y))
            y += line.height()
        layout.endLayout()
        return layout

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_key = None
        self._text_layer = None
        self._bg_surface = None

    def invalidate_background(self):
        """Rebuild the cached backdrop on the next paint (cover fade, resize)."""
        self._bg_surface = None

    def _ensure_layouts(self, base: int):
        page = self._page
        width = max(80, self.width() - 24)
        key = (id(page._lyrics), base, width)
        if key == self._layout_key:
            return
        normal_font = self._font(base)
        active_font = self._font(base, True)
        trans_font = self._font(max(16, base - 8))
        gap = max(12, int(base * 0.9))
        layouts, anchors, heights = [], [], []
        cursor = 0.0
        for line in page._lyrics:
            normal = self._make_layout(line.text, normal_font, width)
            active = self._make_layout(line.text, active_font, width)
            trans = (self._make_layout(line.translation, trans_font, width)
                     if line.translation else None)
            text_h = max(normal.boundingRect().height(),
                         active.boundingRect().height())
            block_h = text_h + ((trans.boundingRect().height() + 6) if trans else 0)
            anchors.append(cursor)
            heights.append(block_h)
            layouts.append((normal, active, trans, text_h))
            cursor += block_h + gap
        self._layouts = layouts
        self._anchors = anchors
        self._heights = heights
        self._layout_key = key

    def _scroll_offset(self, anim_line: float) -> float:
        n = len(self._anchors)
        if n == 0:
            return 0.0
        a = max(0, min(n - 1, int(anim_line)))
        b = min(n - 1, a + 1)
        ca = self._anchors[a] + self._heights[a] / 2.0
        cb = self._anchors[b] + self._heights[b] / 2.0
        return ca + (cb - ca) * (anim_line - a)

    def _paint_background(self, p: QPainter):
        """Blit the same full-page backdrop the parent paints.

        The child draws the page's backdrop with the page's own coordinates
        (translated, clipped to this widget) instead of cropping a scaled
        copy, so both surfaces go through the exact same painter operations
        and their pixels match at the seam — including mid-crossfade.
        """
        page = self._page
        dpr = self.devicePixelRatioF()
        px = QSize(max(1, int(self.width() * dpr)),
                   max(1, int(self.height() * dpr)))
        if self._bg_surface is None or self._bg_surface.size() != px:
            self._bg_surface = QPixmap(px)
            self._bg_surface.setDevicePixelRatio(dpr)
            bp = QPainter(self._bg_surface)
            bp.save()
            bp.translate(-self.x(), -self.y())
            page._paint_background(bp)
            bp.restore()
            bp.end()
        p.drawPixmap(0, 0, self._bg_surface)

    def _render_text_layer(self, progress: float) -> QPixmap | None:
        """Render the masked lyric text for this widget, cached per frame."""
        page = self._page
        if not page._lyrics or progress <= 0.01:
            return None
        base = max(20, min(34, int(self.width() * 0.038)))
        self._ensure_layouts(base)
        if not self._layouts:
            return None

        center_y = page.height() * 0.44 - self.y()
        anim_line = page._lyrics_anim_line
        offset = self._scroll_offset(anim_line)
        active = page._lyrics_active_idx
        half_visible = 5
        accent = page._accent
        n = len(self._layouts)

        dpr = self.devicePixelRatioF()
        px_size = QSize(max(1, int(self.width() * dpr)),
                        max(1, int(self.height() * dpr)))
        if self._text_layer is None or self._text_layer.size() != px_size:
            self._text_layer = QPixmap(px_size)
            self._text_layer.setDevicePixelRatio(dpr)
        self._text_layer.fill(Qt.GlobalColor.transparent)

        tp = QPainter(self._text_layer)
        tp.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i in range(max(0, active - half_visible),
                       min(n, active + half_visible + 1)):
            normal, active_layout, trans, text_h = self._layouts[i]
            y = center_y + self._anchors[i] - offset
            if i == active:
                tp.setOpacity(progress)
                tp.setPen(QColor(accent))
                active_layout.draw(tp, QPointF(0, y))
                if trans is not None:
                    color = QColor(accent)
                    color.setAlphaF(0.55)
                    tp.setPen(color)
                    trans.draw(tp, QPointF(0, y + text_h + 6))
            else:
                dist = abs(i - anim_line)
                fade = max(0.0, 1.0 - dist / (half_visible + 1) * 0.85)
                tp.setOpacity(progress * fade * 0.7)
                tp.setPen(QColor("#8899aa"))
                normal.draw(tp, QPointF(0, y))
        tp.end()

        hh = max(1, self.height())
        fade_top = min(56, max(28, int(hh * 0.16)))
        fade_bottom = min(48, max(24, int(hh * 0.12)))
        stop_top = min(1.0, fade_top / hh)
        stop_bottom = max(stop_top, 1.0 - fade_bottom / hh)
        mask = QLinearGradient(0, 0, 0, hh)
        mask.setColorAt(0.0, QColor(0, 0, 0, 0))
        mask.setColorAt(stop_top, QColor(0, 0, 0, 255))
        mask.setColorAt(stop_bottom, QColor(0, 0, 0, 255))
        mask.setColorAt(1.0, QColor(0, 0, 0, 0))
        mp = QPainter(self._text_layer)
        mp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        mp.fillRect(QRectF(0, 0, self.width(), hh), mask)
        mp.end()
        return self._text_layer

    def draw_text_preview(self, p: QPainter, progress: float):
        """Draw just the lyrics text at this layer's page position.

        Used by the page during the artwork→lyrics morph, while this opaque
        widget is still hidden so it can't cover the moving cover art.
        """
        layer = self._render_text_layer(progress)
        if layer is not None:
            p.drawPixmap(self.x(), self.y(), layer)

    def paintEvent(self, event):
        page = self._page
        progress = page._lyrics_layout_progress
        text = self._render_text_layer(progress)
        if text is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_background(p)
        p.drawPixmap(0, 0, text)
        p.end()


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
        self._cover_sprite_pix: QPixmap | None = None
        self._cover_sprite_key = None
        self._composed_bg: QPixmap | None = None
        self._composed_bg_key = None
        self._blurred_bg: QPixmap | None = None
        self._cached_bg: QPixmap | None = None  # scaled-to-window cached bg
        self._old_cached_bg: QPixmap | None = None  # previous bg during crossfade
        self._old_cached_scaled: QPixmap | None = None  # scaled copy of the above (per-size cache)
        self._bg_fade_progress: float = 1.0  # 0=old, 1=new
        self._bg_px: tuple[int, int] | None = None  # device-pixel size of cache
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
        self._lyrics_anim_duration = 420  # ms — smoother transition
        self._lyrics_scroll_clock = QElapsedTimer()

        self._lyrics_layout_helper = _OpacityHelper(self)
        self._lyrics_layout_helper.opacity = 0.0
        self._lyrics_layout_anim: QPropertyAnimation | None = None

        self._lyrics_scroll_timer = QTimer(self)
        self._lyrics_scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._lyrics_scroll_timer.setInterval(16)  # 60fps, lyrics layer only
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

        # Hero enter/exit transition (cover flies from/to the playback bar).
        self._enter_progress = 1.0
        self._enter_global_rect: QRect | None = None
        self._exit_done = None
        self._enter_direction = "in"
        # 切换瞬间的普通界面快照：开场背景从它淡入，退场淡回它，
        # 消除亮色界面 ↔ 暗色沉浸页之间的一帧硬切（"黑背景突现"）。
        self._underlay: QPixmap | None = None
        self._enter_helper = _OpacityHelper(self)
        self._enter_helper.opacity = 1.0
        self._enter_anim: QPropertyAnimation | None = None
        self._enter_easing = QEasingCurve.Type.OutExpo

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

        # Dedicated lyrics surface (below the top-right buttons).
        self._lyrics_layer = _LyricsLayer(self)
        self._position_lyrics_layer()

    def _position_lyrics_layer(self):
        if not hasattr(self, "_lyrics_layer"):
            return
        w, h = self.width(), self.height()
        left = int(w * 0.42)
        self._lyrics_layer.setGeometry(
            left, 64, max(1, w - left), max(1, h - 64)
        )
        self._lyrics_layer.raise_()

    # ---- Hero enter/exit transition ----
    #
    # Opening from the playback bar no longer slides the whole page. The page
    # appears at full size with its own backdrop; the cover flies from the
    # bar's thumbnail to its immersive position and the texts rise in
    # staggered. No cross-fade of a snapshot: compositing a full-page grab
    # over a live page was both expensive and visually noisy (stale sizes,
    # ghosting libraries), so the bar's cover is the only continuity device.

    def begin_enter_transition(self, cover_global_rect: QRect,
                               duration: int = 560, underlay: QPixmap | None = None):
        self._enter_global_rect = QRect(cover_global_rect)
        self._enter_direction = "in"
        self._exit_done = None
        self._underlay = underlay
        self._set_topbar_buttons_visible(False)
        self._start_enter_anim(0.0, 1.0, duration)

    def begin_exit_transition(self, cover_global_rect: QRect,
                              on_done=None,
                              duration: int = 460,
                              underlay: QPixmap | None = None):
        self._enter_global_rect = QRect(cover_global_rect)
        self._enter_direction = "out"
        self._exit_done = on_done
        self._underlay = underlay
        self._lyrics_layer.hide()
        # 右上角按钮随退场淡出，而不是瞬间消失（进入时页面刚出现，
        # 按钮本来不可见，瞬间隐藏无感，保持原样）
        self._topbar_hide_timer.stop()
        if self._topbar_opacity > 0.01:
            self._animate_topbar(self._topbar_opacity, 0.0, 200)
        else:
            self._set_topbar_buttons_visible(False)
        self._start_enter_anim(1.0, 0.0, duration)

    def _set_topbar_buttons_visible(self, flag: bool):
        for btn in (self._lyrics_btn, self._fullscreen_btn, self._close_btn):
            btn.setVisible(flag)

    def _start_enter_anim(self, start: float, end: float, duration: int):
        if _anim_running(self._enter_anim):
            self._enter_anim.stop()
        self._enter_helper.opacity = start
        self._enter_progress = start
        anim = QPropertyAnimation(self._enter_helper, b"opacity")
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        self._enter_easing = (
            QEasingCurve.Type.OutExpo if end > start
            else QEasingCurve.Type.InCubic)
        anim.setEasingCurve(self._enter_easing)
        anim.valueChanged.connect(self._on_enter_tick)
        anim.finished.connect(self._on_enter_finished)
        anim.start()
        self._enter_anim = anim
        self._update_lyrics_layer()
        self.update()

    def _on_enter_tick(self):
        self._enter_progress = self._enter_helper.opacity
        self.update()

    def _on_enter_finished(self):
        done = self._exit_done
        exiting = self._enter_helper.opacity <= 0.001
        self._enter_progress = 1.0
        self._enter_global_rect = None
        self._exit_done = None
        self._underlay = None
        if exiting:
            self._enter_helper.opacity = 1.0
            if done:
                done()
        else:
            self._update_lyrics_layer()
            # 恢复右上角按钮。opacity 已接近 1 时动画无值变化、回调不触发，
            # 需直接显示；从退场淡出后的低 opacity 进入则用 _show_topbar 淡入
            if self._topbar_opacity > 0.9:
                self._set_topbar_buttons_visible(True)
                self._topbar_hide_timer.start()
            else:
                self._show_topbar()
            self.update()

    def _enter_time(self) -> float:
        """Un-eased fraction (0→1) of the hero transition's wall-clock.

        Staggers and snapshot fades use real time so the easing curve does
        not crush them into the first few frames.
        """
        p = max(0.0, min(1.0, self._enter_progress))
        if self._enter_easing == QEasingCurve.Type.InCubic:
            return (1.0 - p) ** (1.0 / 3.0)
        if p >= 1.0:
            return 1.0
        if p <= 0.0:
            return 0.0
        return max(0.0, min(1.0, -math.log2(1.0 - p) / 10.0))

    def _enter_alpha(self, delay: float = 0.0) -> float:
        """Staggered ease for texts/controls during the hero transition.

        进入按 delay 错峰淡入；退场做镜像淡出（t 从 0→1，控件在
        t = 1-delay 前淡完）：按钮先消失、标题最后，与背景交叉淡化
        同节奏，不会出现"瞬间消失→又淡回来→切走时硬切"。
        """
        if self._enter_global_rect is None:
            return 1.0
        t = self._enter_time()
        if self._enter_direction == "out":
            span = max(0.001, 1.0 - delay)
            a = 1.0 - max(0.0, min(1.0, t / span))
            return a * a * (3.0 - 2.0 * a)
        a = max(0.0, min(1.0, (t - delay) / max(0.001, 1.0 - delay)))
        return a * a * (3.0 - 2.0 * a)

    def _cover_sprite(self) -> QPixmap | None:
        """Square cover pre-scaled once at final device size.

        The flight then only downscales this sprite with the painter's smooth
        transform instead of re-scaling the original 1500px artwork every
        frame.
        """
        src = self._cover_pixmap
        if src is None or src.isNull():
            return None
        dpr = self.devicePixelRatioF()
        target = max(8, min(int(self.height() * 0.38), int(self.width() * 0.35), 380))
        px = max(8, int(target * dpr))
        key = (id(src), px, dpr)
        if self._cover_sprite_pix is not None and self._cover_sprite_key == key:
            return self._cover_sprite_pix
        scaled = src.scaled(px, px,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        if scaled.width() != px or scaled.height() != px:
            scaled = scaled.copy((scaled.width() - px) // 2,
                                 (scaled.height() - px) // 2, px, px)
        scaled.setDevicePixelRatio(dpr)
        self._cover_sprite_pix = scaled
        self._cover_sprite_key = key
        return scaled

    def _cover_draw_rect(self, x: float, y: float, size: float) -> tuple[float, float, float, float]:
        """Interpolate the cover between the bar thumbnail and its target."""
        if self._enter_global_rect is None or self._enter_progress >= 0.999:
            return x, y, size, 12.0
        start = self.mapFromGlobal(self._enter_global_rect.topLeft())
        sx, sy = float(start.x()), float(start.y())
        sw, sh = float(self._enter_global_rect.width()), float(self._enter_global_rect.height())
        ss = min(sw, sh) if min(sw, sh) > 0 else 56.0
        e = self._enter_progress
        return (sx + (x - sx) * e,
                sy + (y - sy) * e,
                ss + (size - ss) * e,
                6.0 + 6.0 * e)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_lyrics_layer()

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
                self._old_cached_scaled = None  # invalidate scaled cache
                self._cover_pixmap = pix
                self._blurred_bg = None  # invalidate
                self._cached_bg = None
                self._start_bg_crossfade()
                return
        self._cover_pixmap = None
        self._blurred_bg = None
        self._old_cached_bg = self._cached_bg  # fade old to empty
        self._old_cached_scaled = None  # invalidate scaled cache
        self._start_bg_crossfade()

    def _start_bg_crossfade(self):
        if self._bg_fade_helper is None:
            self._bg_fade_helper = _OpacityHelper(self)
            self._bg_fade_helper._opacity = 0.0
        if _anim_running(self._bg_fade_anim):
            self._bg_fade_anim.stop()
        self._bg_fade_progress = 0.0
        if hasattr(self, "_lyrics_layer"):
            self._lyrics_layer.invalidate_background()
        self._bg_fade_anim = QPropertyAnimation(self._bg_fade_helper, b"opacity")
        self._bg_fade_anim.setDuration(500)
        self._bg_fade_anim.setStartValue(0.0)
        self._bg_fade_anim.setEndValue(1.0)
        self._bg_fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._bg_fade_anim.valueChanged.connect(self._on_bg_fade_tick)
        self._bg_fade_anim.start()

    def _on_bg_fade_tick(self):
        self._bg_fade_progress = self._bg_fade_helper._opacity
        self._lyrics_layer.invalidate_background()
        self._lyrics_layer.update()
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
        self._lyrics_layer.update()
        self.update()

    def _progress_region(self) -> QRect:
        h = self.height()
        top = max(0, int(h * 0.62))
        return QRect(0, top, self.width(), h - top)

    def set_position(self, ms: int):
        self._position_ms = ms
        self.update(self._progress_region())

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self.update(self._progress_region())

    def set_playing(self, playing: bool):
        self._is_playing = playing
        self.update()

    # ---- Lyrics ----

    def set_lyrics(self, lines: list):
        self._lyrics = lines if lines else []
        self._lyrics_active_idx = -1
        self._lyrics_anim_line = 0.0
        self._lyrics_scroll_timer.stop()
        self._lyrics_layer.lyrics_changed()
        self._update_lyrics_layer()
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
        if _anim_running(self._lyrics_layout_anim):
            self._lyrics_layout_anim.stop()
        self._lyrics_layout_helper.opacity = self._lyrics_layout_progress
        self._lyrics_layout_anim = QPropertyAnimation(self._lyrics_layout_helper, b"opacity")
        self._lyrics_layout_anim.setDuration(400)
        self._lyrics_layout_anim.setStartValue(self._lyrics_layout_progress)
        self._lyrics_layout_anim.setEndValue(target)
        self._lyrics_layout_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._lyrics_layout_anim.valueChanged.connect(self._on_layout_progress_changed)
        self._lyrics_layout_anim.start()
        self._update_lyrics_layer()
        self.lyricsToggled.emit(visible)

    def _update_lyrics_layer(self):
        """Only hand rendering to the opaque child once the morph has settled.

        During the artwork→lyrics transition the lyrics text is painted by the
        page itself (fading with the same progress as the cover/title morph),
        so the child's opaque surface never covers the moving cover art.
        """
        settled = (
            self._lyrics_mode
            and bool(self._lyrics)
            and self._lyrics_layout_progress >= 0.999
            and self._enter_global_rect is None
        )
        self._lyrics_layer.setVisible(settled)

    def _on_layout_progress_changed(self):
        self._lyrics_layout_progress = self._lyrics_layout_helper.opacity
        self._update_lyrics_layer()
        self._lyrics_layer.update()
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
                self._lyrics_scroll_clock.start()
                self._lyrics_scroll_timer.start()
            if self._lyrics_mode and self._lyrics_layout_progress > 0.01:
                if self._lyrics_layer.isVisible():
                    self._lyrics_layer.update()
                else:
                    self.update()  # morph-time preview is painted by the page

    def _tick_lyrics_scroll(self):
        elapsed = self._lyrics_scroll_clock.elapsed()
        t = min(1.0, elapsed / self._lyrics_anim_duration)
        # smoothstep: zero velocity at both ends
        ease = t * t * (3.0 - 2.0 * t)
        self._lyrics_anim_line = self._lyrics_anim_start + (self._lyrics_anim_target - self._lyrics_anim_start) * ease
        if t >= 1.0:
            self._lyrics_scroll_timer.stop()
        # Only the dedicated lyrics layer repaints; during the morph the
        # page owns the preview and repaints itself.
        if self._lyrics_layer.isVisible():
            self._lyrics_layer.update()
        else:
            self.update()

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
        """Animate buttons opacity."""
        if _anim_running(self._fade_anim):
            self._fade_anim.stop()
        self._opacity_helper.opacity = start
        self._fade_anim = QPropertyAnimation(self._opacity_helper, b"opacity")
        self._fade_anim.setDuration(duration)
        self._fade_anim.setStartValue(start)
        self._fade_anim.setEndValue(end)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_anim.valueChanged.connect(self._on_opacity_changed)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._fade_anim.start()

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
        if _anim_running(self._topbar_fade_anim):
            self._topbar_fade_anim.stop()
        self._topbar_opacity_helper.opacity = start
        self._topbar_fade_anim = QPropertyAnimation(self._topbar_opacity_helper, b"opacity")
        self._topbar_fade_anim.setDuration(duration)
        self._topbar_fade_anim.setStartValue(start)
        self._topbar_fade_anim.setEndValue(end)
        self._topbar_fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._topbar_fade_anim.valueChanged.connect(self._on_topbar_opacity_changed)
        self._topbar_fade_anim.finished.connect(self._on_topbar_fade_finished)
        self._topbar_fade_anim.start()

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
        # 拆窗销毁过程中动画对象可能已被 C++ 侧删除，访问前需防护
        for attr in ("_fade_anim", "_topbar_fade_anim", "_bg_fade_anim"):
            if _anim_running(getattr(self, attr, None)):
                getattr(self, attr).stop()

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

    def _ensure_bg_cache(self):
        """Scale the blurred cover once per page size, in device pixels."""
        dpr = self.devicePixelRatioF()
        px = (max(1, int(self.width() * dpr)),
              max(1, int(self.height() * dpr)))
        if (self._cached_bg is not None and self._bg_px == px
                and self._cached_bg.devicePixelRatio() == dpr):
            return
        if self._blurred_bg is None:
            return
        self._cached_bg = self._blurred_bg.scaled(
            px[0], px[1],
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cached_bg.setDevicePixelRatio(dpr)
        self._bg_px = px

    def _scaled_old_bg(self) -> QPixmap | None:
        old = self._old_cached_bg
        if old is None or old.isNull():
            return None
        dpr = self.devicePixelRatioF()
        px = (max(1, int(self.width() * dpr)),
              max(1, int(self.height() * dpr)))
        if (old.devicePixelRatio() != dpr
                or (old.width(), old.height()) != px):
            old = old.scaled(px[0], px[1],
                             Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
            old.setDevicePixelRatio(dpr)
            self._old_cached_bg = old
        return old

    def _compose_background(self) -> QPixmap:
        """Render gradient + blurred cover + dark overlay once per state."""
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        pxw, pxh = max(1, int(w * dpr)), max(1, int(h * dpr))
        pix = self._composed_bg
        if pix is None or pix.width() != pxw or pix.height() != pxh:
            pix = QPixmap(pxw, pxh)  # reuse the buffer across fade ticks
        pix.setDevicePixelRatio(dpr)
        cp = QPainter(pix)
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor("#0d0d1a"))
        grad.setColorAt(1.0, QColor("#1a1a2e"))
        cp.fillRect(0, 0, w, h, grad)

        has_cover = bool(self._cover_pixmap and not self._cover_pixmap.isNull())
        if has_cover:
            if self._blurred_bg is None:
                self._blurred_bg = _blur_pixmap(self._cover_pixmap)
            self._ensure_bg_cache()

        old = self._scaled_old_bg()
        new = self._cached_bg if has_cover else None
        t = self._bg_fade_progress
        if old is not None or new is not None:
            if t < 1.0 and old is not None:
                cp.setOpacity(1.0 - t)
                cp.drawPixmap(0, 0, old)
                cp.setOpacity(1.0)
            if t > 0 and new is not None:
                cp.setOpacity(t)
                cp.drawPixmap(0, 0, new)
                cp.setOpacity(1.0)
            cp.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))
        cp.end()
        self._composed_bg = pix
        self._composed_bg_key = (
            id(self._cover_pixmap), id(self._blurred_bg), id(self._cached_bg),
            id(self._old_cached_bg), round(t, 3), w, h, dpr)
        return pix

    def _paint_background(self, p: QPainter):
        """Paint the full-page backdrop with a single blit when idle.

        Shared verbatim by paintEvent and the lyrics child (which translates
        by its own offset and lets the clip restrict it), so the two never
        drift apart by a resampling or opacity-compositing step.
        """
        w, h = self.width(), self.height()
        key = (id(self._cover_pixmap), id(self._blurred_bg),
               id(self._cached_bg), id(self._old_cached_bg),
               round(self._bg_fade_progress, 3), w, h,
               self.devicePixelRatioF())
        if self._composed_bg is None or self._composed_bg_key != key:
            self._compose_background()
        if self._underlay is not None and self._enter_global_rect is not None:
            # 真交叉淡化：底层是切换瞬间的普通界面快照，沉浸页背景在其上
            # 淡入/淡出。第一帧看到的是原界面（不是黑色），收尾时切回普通
            # 界面也无跳变。快照只在过渡的几百毫秒内使用。
            # QRectF 原生接受 float：快照按自身 dpr 缩放回逻辑尺寸，
            # HiDPI（dpr≠1）与过渡中改窗口尺寸都正确拉伸。
            u_dpr = self._underlay.devicePixelRatio() or 1.0
            p.drawPixmap(
                QRectF(0, 0,
                       self._underlay.width() / u_dpr,
                       self._underlay.height() / u_dpr),
                self._underlay,
                QRectF(0, 0, self._underlay.width(), self._underlay.height()))
            if self._enter_direction == "in":
                # 背景在前 40% 时间内淡入，与封面起飞同步
                t = max(0.0, min(1.0, self._enter_time() / 0.4))
                alpha = t * t * (3.0 - 2.0 * t)
            else:
                # 关闭：背景随下降的封面整体淡出，结束时与切回普通界面无缝
                travel = max(0.0, min(1.0, 1.0 - self._enter_progress))
                alpha = 1.0 - travel * travel * (3.0 - 2.0 * travel)
            if alpha > 0.002:
                p.setOpacity(alpha)
                p.drawPixmap(0, 0, self._composed_bg)
                p.setOpacity(1.0)
            return
        # On the way in the backdrop starts slightly dimmed and brightens over
        # ~150ms. It is never hidden behind a black overlay: a fade from black
        # reads as a black mask flashing over the whole window.
        alpha = 1.0
        if self._enter_global_rect is not None:
            if self._enter_direction == "in":
                t = max(0.0, min(1.0, self._enter_time() / 0.4))
                alpha = 0.6 + 0.4 * (t * t * (3.0 - 2.0 * t))
            else:
                # Closing: dim with the descending cover, mirroring the open.
                travel = max(0.0, min(1.0, 1.0 - self._enter_progress))
                alpha = 1.0 - 0.4 * (travel * travel * (3.0 - 2.0 * travel))
        if alpha < 0.999:
            p.fillRect(0, 0, w, h, QColor("#07070c"))
            p.setOpacity(alpha)
            p.drawPixmap(0, 0, self._composed_bg)
            p.setOpacity(1.0)
        else:
            p.drawPixmap(0, 0, self._composed_bg)

    def _draw_meta_line(self, p: QPainter, text: str, font: QFont, color: QColor,
                        y: float, line_h: int, progress: float,
                        cover_x: float, cover_size: float,
                        alpha: float = 1.0, rise: float = 0.0):
        """One metadata line, gliding from page-centered to under-cover-left.

        The rect's left edge and max width both interpolate with the layout
        morph, so the title block travels with the cover instead of jumping
        at the half-way point. `alpha`/`rise` drive the hero entry stagger.
        """
        if alpha <= 0.002:
            return
        prev_opacity = p.opacity()
        p.setOpacity(prev_opacity * alpha)
        p.setFont(font)
        p.setPen(color)
        y += rise
        fm = QFontMetrics(font)
        max_w = 500.0 + (cover_size - 500.0) * progress
        elided = fm.elidedText(text or "", Qt.TextElideMode.ElideRight,
                               max(10, int(max_w) - 10))
        text_w = fm.horizontalAdvance(elided)
        # Stay glued to the cover: centered under it while in artwork mode,
        # left-aligned with it in lyrics mode, blending between the two.
        x_centered = cover_x + cover_size / 2.0 - text_w / 2.0
        x = x_centered + (cover_x - x_centered) * progress
        p.drawText(QRectF(x, y, max(10, max_w), line_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   elided)
        p.setOpacity(prev_opacity)

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
        self._paint_background(p)

        # ---- Lyrics: morph-time preview until the settled layer takes over ----
        # Painted under the cover/metadata so the cover glides over the
        # emerging lyrics instead of having text stamped on top of it.
        # Not gated on _lyrics_mode: on the way out the flag is already
        # False while progress is still fading 1→0, and the fade must play.
        if (self._lyrics_layout_progress > 0.01
                and not self._lyrics_layer.isVisible()):
            self._lyrics_layer.draw_text_preview(
                p, self._lyrics_layout_progress * self._enter_alpha(0.25))

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
        # During the hero transition the cover is drawn at the interpolated
        # rect between the playback bar thumbnail and this page's cover.
        d_x, d_y, d_sz, d_radius = self._cover_draw_rect(cover_x, cover_y, cover_size)
        d_sz = max(8, int(round(d_sz)))
        d_x = int(round(d_x))
        d_y = int(round(d_y))
        hero = 1.0 if self._enter_global_rect is None else self._enter_progress
        if self._cover_pixmap and not self._cover_pixmap.isNull():
            # Shadow
            shadow = QPainterPath()
            shadow.addRoundedRect(QRectF(d_x + 3, d_y + 5,
                                         d_sz, d_sz), d_radius, d_radius)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(10 + (shadow_alpha - 10) * hero)))
            p.drawPath(shadow)

            # Cover with rounded corners
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(d_x, d_y, d_sz, d_sz),
                                d_radius, d_radius)
            p.setClipPath(clip)

            sprite = self._cover_sprite()
            if sprite is not None:
                # 1:1 at rest; during the flight the painter downscales the
                # cached device-size sprite with smoothing (no per-frame
                # QPixmap.scaled of the full artwork).
                # Source rect is in *device* pixels here, not logical ones:
                # Qt does not divide it by the pixmap's DPR, so using the
                # logical size would take only the top-left quarter of the
                # sprite (and clip the album title off the bottom).
                p.drawPixmap(
                    QRectF(d_x, d_y, d_sz, d_sz), sprite,
                    QRectF(0, 0, sprite.width(), sprite.height()))
            p.setClipping(False)

            # Subtle border
            p.setPen(QPen(QColor(255, 255, 255, 20), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(d_x, d_y, d_sz, d_sz),
                              d_radius, d_radius)
        else:
            # Placeholder
            rect = QRectF(d_x, d_y, d_sz, d_sz)
            grad = QLinearGradient(d_x, d_y,
                                   d_x + d_sz, d_y + d_sz)
            grad.setColorAt(0.0, QColor("#1e1e40"))
            grad.setColorAt(1.0, QColor("#2d1b69"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(rect, d_radius, d_radius)
            font = QFont()
            font.setPointSize(max(6, d_sz // 4))
            p.setFont(font)
            p.setPen(QColor("#a78bfa"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "♪")

        # ---- Layer 1: Track info (with metadata opacity) ----
        p.setOpacity(meta_ease)
        text_y = cover_y + cover_size + 32
        title_alpha = self._enter_alpha(0.20)
        meta_alpha = self._enter_alpha(0.28)
        title_rise = (1.0 - title_alpha) * 16.0
        meta_rise = (1.0 - meta_alpha) * 16.0

        # Title
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        self._draw_meta_line(p, self._title, title_font, QColor("#ffffff"),
                             text_y, 36, progress, cover_x, cover_size,
                             alpha=title_alpha, rise=title_rise)
        text_y += 36 + 8

        # Artist
        artist_font = QFont()
        artist_font.setPointSize(14)
        self._draw_meta_line(p, self._artist, artist_font,
                             QColor(self._accent.lighter(130).name()),
                             text_y, 24, progress, cover_x, cover_size,
                             alpha=meta_alpha, rise=meta_rise)
        text_y += 24 + 4

        # Album
        album_font = QFont()
        album_font.setPointSize(11)
        self._draw_meta_line(p, self._album, album_font, QColor("#8899aa"),
                             text_y, 20, progress, cover_x, cover_size,
                             alpha=meta_alpha, rise=meta_rise)
        p.setOpacity(1.0)

        # Lyrics are rendered by the dedicated _LyricsLayer child widget.

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

        # Apply auto-hide + lyrics mode + hero-entry opacity to controls
        ctrl_alpha = self._enter_alpha(0.38)
        combined_btn_opacity = self._buttons_opacity * controls_opacity * ctrl_alpha
        progress_opacity *= ctrl_alpha
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
        if self._quality_text and ctrl_alpha > 0.002:
            p.setOpacity(ctrl_alpha)
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
            p.setOpacity(1.0)

        p.end()

    # ---- Lyrics rendering ----

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
