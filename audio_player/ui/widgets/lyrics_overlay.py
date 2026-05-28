from PyQt6.QtWidgets import QWidget, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPen, QFont, QLinearGradient,
                         QPainterPath, QFontMetrics)
from dataclasses import dataclass
from typing import List
from audio_player.app import current_theme_mode, current_accent
from audio_player.i18n import _


@dataclass
class LyricsLine:
    time_ms: int
    text: str
    translation: str = ""  # paired bilingual translation line


class LyricsOverlay(QWidget):
    VISIBLE_LINES = 7  # odd number for centering
    fullscreenRequested = pyqtSignal()
    searchRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lyrics: List[LyricsLine] = []
        self._current_ms = 0
        self._active_idx = -1
        self._visible = True
        self._duration_ms = 0
        self._line_height = 40
        self._translation_gap = 6
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("")

        # Scroll animation
        self._anim_offset_y = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._update_anim)

        # Top-right buttons (hidden until hover)
        btn_style = (
            "QPushButton { background: #1a1a2e; color: #999; border: none; "
            "border-radius: 12px; font-size: 12px; }"
            "QPushButton:hover { background: #2a2a4a; color: #fff; }"
        )
        self._fullscreen_btn = QPushButton("⛶", self)
        self._fullscreen_btn.setFixedSize(24, 24)
        self._fullscreen_btn.setStyleSheet(btn_style)
        self._fullscreen_btn.setToolTip(_("lyrics.fullscreen_entry"))
        self._fullscreen_btn.clicked.connect(self.fullscreenRequested)
        self._fullscreen_btn.hide()

        self._search_btn = QPushButton("?", self)
        self._search_btn.setFixedSize(24, 24)
        self._search_btn.setStyleSheet(btn_style)
        self._search_btn.setToolTip(_("lyrics.search_online"))
        self._search_btn.clicked.connect(self.searchRequested)
        self._search_btn.hide()

        self._overlay_hovered = False
        self._loading = False

    def set_lyrics(self, lines: List[LyricsLine]):
        self._lyrics = sorted(lines, key=lambda x: x.time_ms)
        self._active_idx = -1
        self._anim_offset_y = 0.0
        self._fullscreen_btn.setVisible(bool(self._lyrics))
        if not self._lyrics:
            self.hide()
        self.update()

    def has_lyrics(self) -> bool:
        return len(self._lyrics) > 0

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
            # Direction-aware slide: forward → slide up, backward → slide down
            direction = 1 if new_idx > self._active_idx else -1
            self._anim_offset_y = self._line_height * direction
            self._active_idx = new_idx
            self._anim_timer.start()
            self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms

    def set_line_height(self, px: int):
        self._line_height = px
        self.update()

    def set_translation_gap(self, px: int):
        self._translation_gap = px
        self.update()

    def set_loading_state(self, loading: bool):
        self._loading = loading
        if loading:
            self._search_btn.hide()
            self._search_btn.setEnabled(False)
        else:
            self._search_btn.setEnabled(True)
        self.update()

    def _update_anim(self):
        """Smooth exponential ease-out toward zero."""
        self._anim_offset_y *= 0.82
        if abs(self._anim_offset_y) < 0.5:
            self._anim_offset_y = 0.0
            self._anim_timer.stop()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fullscreen_btn.move(self.width() - 32, 8)
        self._search_btn.move(self.width() - 60, 8)

    def enterEvent(self, event):
        self._overlay_hovered = True
        if not self._loading:
            self._search_btn.show()
        if self._lyrics:
            self._fullscreen_btn.show()

    def leaveEvent(self, event):
        self._overlay_hovered = False
        self._fullscreen_btn.hide()
        self._search_btn.hide()

    def showEvent(self, event):
        super().showEvent(event)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._fullscreen_btn.hide()
        self._search_btn.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        is_light = current_theme_mode() == "light"

        # Fully opaque background
        painter.setPen(Qt.PenStyle.NoPen)
        if is_light:
            painter.setBrush(QColor("#eeeeee"))
        else:
            painter.setBrush(QColor("#12121a"))
        painter.drawRoundedRect(QRectF(0, 0, w, h), 0, 0)

        no_lyrics_color = QColor("#888") if is_light else QColor("#999")
        if not self._lyrics:
            painter.setPen(no_lyrics_color)
            font = QFont()
            font.setPointSize(14)
            painter.setFont(font)
            if self._loading:
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("lyrics.searching"))
            else:
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("lyrics.no_lyrics"))
            painter.end()
            return

        # Untimed lyrics (embedded, no timestamps): show all lines as static text
        is_untimed = all(l.time_ms == 0 for l in self._lyrics)
        if is_untimed:
            font = QFont()
            font.setPointSize(13)
            painter.setFont(font)
            fm = QFontMetrics(font)
            has_translations = any(l.translation for l in self._lyrics)
            line_h = fm.height() + (10 if has_translations else 6)
            total_h = 0
            for l in self._lyrics:
                total_h += line_h + (fm.height() // 2 if l.translation else 0)
            start_y = max(10, int((h - total_h) / 2))

            text_color = QColor(80, 80, 80, 200) if is_light else QColor(200, 200, 200, 200)
            trans_color = QColor(120, 120, 120, 140) if is_light else QColor(160, 160, 160, 140)

            for i, line in enumerate(self._lyrics):
                y = start_y + sum(
                    line_h + (fm.height() // 2 if self._lyrics[j].translation else 0)
                    for j in range(i)
                )
                text = line.text
                text_width = fm.horizontalAdvance(text)
                x = (w - text_width) / 2

                painter.setPen(text_color)
                painter.drawText(QPointF(x, y + fm.ascent()), text)

                if line.translation:
                    trans_font = QFont()
                    trans_font.setPointSize(10)
                    trans_fm = QFontMetrics(trans_font)
                    trans_width = trans_fm.horizontalAdvance(line.translation)
                    trans_x = (w - trans_width) / 2
                    trans_y = y + fm.height() + trans_fm.ascent()
                    painter.setPen(trans_color)
                    painter.setFont(trans_font)
                    painter.drawText(QPointF(trans_x, trans_y), line.translation)
                    painter.setFont(font)

            painter.end()
            return

        # Compute vertical shift for active line with translation
        active_has_trans = bool(
            0 <= self._active_idx < len(self._lyrics)
            and self._lyrics[self._active_idx].translation
        )
        gap = self._translation_gap
        shift = (gap + 6) if active_has_trans else 0

        center_y = h / 2 - shift
        half_visible = self.VISIBLE_LINES // 2

        # Theme-aware colors
        inactive_base = QColor(80, 80, 80) if is_light else QColor(200, 200, 200)
        trans_active = QColor(100, 100, 140) if is_light else QColor(180, 180, 220)
        trans_inactive = QColor(120, 120, 120) if is_light else QColor(160, 160, 160)

        for offset in range(-half_visible, half_visible + 1):
            idx = self._active_idx + offset
            if idx < 0 or idx >= len(self._lyrics):
                continue

            y = center_y + offset * self._line_height + self._anim_offset_y
            line = self._lyrics[idx]
            text = line.text
            translation = line.translation

            # Font size and opacity based on distance from center
            dist = abs(offset)
            alpha = int(255 * (1.0 - dist / (half_visible + 1) * 0.85))
            font_size = 16 - dist * 3

            font = QFont()
            font.setPointSize(font_size)
            font.setBold(dist == 0)
            painter.setFont(font)

            # Center text horizontally
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(text)
            x = (w - text_width) / 2

            # Color: accent gradient for active line
            if dist == 0:
                accent = current_accent()
                hl = accent.lighter(130)
                hl2 = accent.lighter(160)
                grad = QLinearGradient(x, y, x + text_width, y)
                grad.setColorAt(0.0, hl)
                grad.setColorAt(0.5, hl2)
                grad.setColorAt(1.0, hl)
                painter.setPen(QPen(grad, 0))
            else:
                inactive_base.setAlpha(alpha)
                painter.setPen(inactive_base)

            # When active line has translation, nudge original text up slightly
            text_y_offset = 2 if (dist == 0 and translation) else 0
            painter.drawText(QPointF(x, y + font_size * 0.3 - text_y_offset), text)

            # Translation line (smaller, dimmer, below original)
            if translation:
                trans_font_size = max(9, font_size - 3)
                trans_font = QFont()
                trans_font.setPointSize(trans_font_size)
                trans_fm = QFontMetrics(trans_font)
                trans_width = trans_fm.horizontalAdvance(translation)
                trans_x = (w - trans_width) / 2
                trans_y = y + font_size * 0.3 + gap + trans_fm.ascent()
                trans_alpha = int(alpha * 0.75)
                if dist == 0:
                    trans_active.setAlpha(max(80, trans_alpha))
                    painter.setPen(trans_active)
                else:
                    trans_inactive.setAlpha(max(40, trans_alpha))
                    painter.setPen(trans_inactive)
                painter.setFont(trans_font)
                painter.drawText(QPointF(trans_x, trans_y), translation)

        painter.end()
