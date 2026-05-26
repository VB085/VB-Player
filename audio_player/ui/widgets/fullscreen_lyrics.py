from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton)
from PyQt6.QtCore import Qt, QTimer, QSettings, QRectF
from PyQt6.QtGui import (QPainter, QColor, QFont, QPen, QFontMetrics,
                         QLinearGradient, QPainterPath, QKeyEvent, QMouseEvent,
                         QBrush)
from PyQt6.QtWidgets import QGraphicsOpacityEffect
from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _
from .lyrics_overlay import LyricsLine


class FullscreenLyricsWindow(QWidget):
    """Frameless fullscreen lyrics display with large text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet("background:#0a0a0f;")

        self._lyrics: list[LyricsLine] = []
        self._current_ms = 0
        self._active_idx = -1
        self._duration_ms = 0
        self._meta = None
        self._mouse_moved = False

        # Hide cursor + UI after inactivity
        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(3000)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_idle)
        self.setMouseTracking(True)

        # Animation state
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._anim_line: float = -1.0
        self._anim_target: float = -1.0
        self._anim_start: float = -1.0
        self._anim_elapsed: int = 0
        self._anim_duration: int = 250
        self._entrance_opacity: float = 1.0
        self._ui_opacity: float = 1.0
        self._ui_target_opacity: float = 1.0

        # Close button (top-right, hidden until mouse moves)
        self._close_btn = QPushButton("✕", self)
        self._close_btn.setFixedSize(36, 36)
        self._close_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.08);color:#888;border:none;"
            "border-radius:18px;font-size:16px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.2);color:#fff;}"
        )
        self._close_btn.clicked.connect(self.hide)
        self._close_btn_effect = QGraphicsOpacityEffect(self)
        self._close_btn_effect.setOpacity(0.0)
        self._close_btn.setGraphicsEffect(self._close_btn_effect)
        self._close_btn.hide()

        # Audio spec bar at bottom
        self._spec_bar = QLabel(self)
        self._spec_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spec_bar.setStyleSheet(
            "color:#444;font-size:11px;font-family:monospace;"
            "background:transparent;padding:8px;"
        )
        self._spec_bar_effect = QGraphicsOpacityEffect(self)
        self._spec_bar_effect.setOpacity(0.0)
        self._spec_bar.setGraphicsEffect(self._spec_bar_effect)
        self._spec_bar.hide()

    def set_lyrics(self, lines: list[LyricsLine]):
        self._lyrics = sorted(lines, key=lambda x: x.time_ms)
        self._active_idx = -1
        self._anim_line = -1.0
        self._anim_target = -1.0
        self.update()

    def set_position(self, ms: int):
        self._current_ms = ms
        if not self._lyrics:
            return
        new_idx = -1
        for i, line in enumerate(self._lyrics):
            if line.time_ms <= ms:
                new_idx = i
            else:
                break
        if new_idx != self._active_idx:
            old_idx = self._active_idx
            self._active_idx = new_idx
            # Jump instantly if gap is large (seek) otherwise animate
            if old_idx < 0 or abs(new_idx - old_idx) > 10:
                self._anim_line = float(new_idx)
                self._anim_target = float(new_idx)
            else:
                self._anim_start = self._anim_line if self._anim_line >= 0 else float(old_idx)
                self._anim_target = float(new_idx)
                self._anim_elapsed = 0
                self._anim_timer.start()
            self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms

    def set_meta(self, meta):
        self._meta = meta
        self._update_spec_bar()

    def _update_spec_bar(self):
        show = self._setting("lyrics_show_spec", True)
        if show and self._meta:
            parts = []
            if self._meta.format:
                parts.append(self._meta.format.upper())
            if self._meta.sample_rate:
                parts.append(f"{self._meta.sample_rate / 1000:.1f}kHz" if self._meta.sample_rate >= 1000
                             else f"{self._meta.sample_rate}Hz")
            if self._meta.bits_per_sample:
                parts.append(f"{self._meta.bits_per_sample}bit")
            if self._meta.bitrate:
                parts.append(f"{self._meta.bitrate // 1000}kbps" if self._meta.bitrate >= 1000
                             else f"{self._meta.bitrate}bps")
            if self._meta.channels:
                ch = {1: "Mono", 2: "Stereo"}.get(self._meta.channels, f"{self._meta.channels}ch")
                parts.append(ch)
            self._spec_bar.setText("  |  ".join(parts))
            self._spec_bar.show()
            self._spec_bar_effect.setOpacity(self._ui_opacity)
        else:
            self._spec_bar.hide()

    def _setting(self, key: str, default):
        return QSettings("VBPlayer", "VB Player").value(key, default)

    def showEvent(self, event):
        super().showEvent(event)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._mouse_moved = False
        self._entrance_opacity = 0.0
        self._ui_opacity = 0.0
        self._ui_target_opacity = 0.0
        self._close_btn_effect.setOpacity(0.0)
        self._spec_bar_effect.setOpacity(0.0)
        self._close_btn.hide()
        self._hide_timer.start()
        self._anim_timer.start()
        self._update_spec_bar()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._anim_timer.stop()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._mouse_moved:
            self._mouse_moved = True
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._close_btn.show()
        self._ui_target_opacity = 1.0
        self._hide_timer.start()
        self._anim_timer.start()
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def _on_idle(self):
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._ui_target_opacity = 0.0
        self._anim_timer.start()
        self._mouse_moved = False

    def _anim_tick(self):
        """60fps animation loop — interpolates scroll, entrance, and UI opacity."""
        changed = False

        # Line scroll animation
        if self._anim_target >= 0 and abs(self._anim_line - self._anim_target) > 0.001:
            self._anim_elapsed += 16
            t = min(1.0, self._anim_elapsed / self._anim_duration)
            # ease-out cubic
            t = 1.0 - (1.0 - t) ** 3
            self._anim_line = self._anim_start + (self._anim_target - self._anim_start) * t
            if t >= 1.0:
                self._anim_line = self._anim_target
            changed = True

        # Entrance opacity animation (0 → 1)
        if self._entrance_opacity < 1.0:
            self._entrance_opacity = min(1.0, self._entrance_opacity + 0.05)
            changed = True

        # UI opacity animation
        if abs(self._ui_opacity - self._ui_target_opacity) > 0.001:
            delta = self._ui_target_opacity - self._ui_opacity
            self._ui_opacity += delta * 0.15  # smooth lerp
            if abs(delta) < 0.002:
                self._ui_opacity = self._ui_target_opacity
            self._close_btn_effect.setOpacity(self._ui_opacity)
            self._spec_bar_effect.setOpacity(self._ui_opacity)
            if self._ui_opacity < 0.01 and self._ui_target_opacity < 0.01:
                self._close_btn.hide()
            changed = True

        if changed:
            self.update()

        # Stop timer when all animations are done
        line_done = (self._anim_target < 0 or
                     abs(self._anim_line - self._anim_target) < 0.001)
        if line_done and self._entrance_opacity >= 1.0 and abs(self._ui_opacity - self._ui_target_opacity) < 0.001:
            self._anim_timer.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._close_btn.move(self.width() - 48, 12)
        self._spec_bar.setGeometry(0, self.height() - 36, self.width(), 30)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(self.rect(), QColor("#0a0a0f"))

        if not self._lyrics:
            painter.setPen(QColor("#555"))
            font = QFont()
            font.setPointSize(18)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("lyrics.no_lyrics"))
            painter.end()
            return

        # Untimed lyrics: show all centered
        is_untimed = all(l.time_ms == 0 for l in self._lyrics)
        if is_untimed:
            self._paint_untimed(painter)
            painter.end()
            return

        # Apply entrance opacity to timed content
        painter.setOpacity(self._entrance_opacity)

        # Settings
        font_size = int(self._setting("lyrics_font_size", 32) or 32)
        line_height = int(self._setting("lyrics_fullscreen_line_height", 60) or 60)
        letter_spacing = int(self._setting("lyrics_letter_spacing", 2) or 2)

        accent = current_accent()
        half_visible = 5
        center_y = h / 2

        # Use animated float for smooth scrolling
        anim_line = self._anim_line if self._anim_line >= 0 else float(self._active_idx)

        for offset in range(-half_visible, half_visible + 1):
            idx = self._active_idx + offset
            if idx < 0 or idx >= len(self._lyrics):
                continue

            # Smooth scroll: offset from animated position instead of integer index
            float_dist = idx - anim_line
            y = center_y + float_dist * line_height
            line = self._lyrics[idx]
            text = line.text
            translation = line.translation

            dist = abs(float_dist)
            alpha = int(255 * (1.0 - dist / (half_visible + 1) * 0.9))
            fs = font_size - dist * 4
            fs = max(10, fs)

            font = QFont()
            font.setPointSize(fs)
            if letter_spacing:
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
            font.setBold(offset == 0)
            painter.setFont(font)

            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(text)
            x = (w - text_width) / 2

            if offset == 0:
                hl = accent.lighter(140)
                hl2 = accent.lighter(180)
                grad = QLinearGradient(x, int(y), x + text_width, int(y))
                grad.setColorAt(0.0, hl)
                grad.setColorAt(0.5, hl2)
                grad.setColorAt(1.0, hl)
                painter.setPen(QPen(grad, 0))
            else:
                c = QColor(180, 180, 180, alpha)
                painter.setPen(c)

            ty = y + fs * 0.35
            painter.drawText(int(x), int(ty), text)

            if translation and dist <= 2:
                t_fs = max(10, fs - 6)
                t_font = QFont()
                t_font.setPointSize(t_fs)
                if letter_spacing:
                    t_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
                t_fm = QFontMetrics(t_font)
                t_w = t_fm.horizontalAdvance(translation)
                t_x = (w - t_w) / 2
                t_y = ty + fm.height() * 0.4 + 8
                t_alpha = int(alpha * 0.7)
                t_color = QColor(140, 140, 180, max(40, t_alpha))
                painter.setPen(t_color)
                painter.setFont(t_font)
                painter.drawText(int(t_x), int(t_y), translation)

        painter.end()

    def _paint_untimed(self, painter: QPainter):
        w = self.width()
        h = self.height()

        # Apply entrance opacity
        painter.setOpacity(self._entrance_opacity)

        font_size = int(self._setting("lyrics_font_size", 32) or 32)
        letter_spacing = int(self._setting("lyrics_letter_spacing", 2) or 2)

        has_trans = any(l.translation for l in self._lyrics)
        font = QFont()
        font.setPointSize(font_size)
        if letter_spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
        t_font = QFont()
        t_font.setPointSize(max(10, font_size - 6))
        if letter_spacing:
            t_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)

        fm = QFontMetrics(font)
        t_fm = QFontMetrics(t_font)

        gap = fm.height() + (t_fm.height() + 8 if has_trans else 4)
        total = sum(gap for l in self._lyrics)
        if has_trans:
            total += sum((t_fm.height() + 4) for l in self._lyrics if l.translation)

        y = (h - total) / 2

        for line in self._lyrics:
            text = line.text
            tw = fm.horizontalAdvance(text)
            x = (w - tw) / 2

            painter.setFont(font)
            painter.setPen(QColor(200, 200, 200, 200))
            painter.drawText(int(x), int(y + fm.ascent()), text)
            y += fm.height() + 4

            if line.translation:
                tw2 = t_fm.horizontalAdvance(line.translation)
                x2 = (w - tw2) / 2
                painter.setFont(t_font)
                painter.setPen(QColor(140, 140, 180, 140))
                painter.drawText(int(x2), int(y + t_fm.ascent()), line.translation)
                y += t_fm.height() + 8
