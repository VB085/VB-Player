from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (QPainter, QColor, QPen, QLinearGradient, QPainterPath, QRadialGradient)
import numpy as np
from enum import IntEnum
from audio_player.app import current_theme_mode, current_accent
from .lyrics_overlay import LyricsOverlay, LyricsLine


class SpectrumMode(IntEnum):
    Bars = 0
    Line = 1
    Circular = 2


class SpectrumWidget(QWidget):
    BAR_COUNT = 64
    FPS = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("")
        self._mode = SpectrumMode.Bars
        self._levels = np.zeros(self.BAR_COUNT, dtype=np.float64)
        self._peaks = np.zeros(self.BAR_COUNT, dtype=np.float64)
        self._peak_decay = 0.96
        self._animation_speed = 0.15
        self._spectrum_cache: np.ndarray | None = None
        self._current_pos_ratio = 0.0
        self._sample_rate = 44100

        # Pre-computed color tables — rebuilt on accent change, not every frame
        self._bar_colors: list[QColor] = []
        self._peak_color = QColor(255, 255, 255, 180)
        self._rebuild_colors()

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // self.FPS)
        self._timer.timeout.connect(self.update)
        self._timer.start()

        # Lyrics overlay as child widget
        self._lyrics = LyricsOverlay(self)
        self._lyrics.hide()
        self._lyrics_visible = False
        self._has_lyrics = False

    def _rebuild_colors(self):
        """Pre-compute bar gradient colors from current accent — called once on accent change."""
        accent = current_accent()
        self._bar_colors = []
        for i in range(self.BAR_COUNT):
            t = i / self.BAR_COUNT
            self._bar_colors.append(QColor(
                int(accent.red() * (1 - t) + 6 * t),
                int(accent.green() * (1 - t) + 182 * t),
                int(accent.blue() * (1 - t) + 212 * t),
                200,
            ))
        self._peak_color = QColor(255, 255, 255, 180)

    def refresh_accent(self):
        """Rebuild color tables when accent changes."""
        self._rebuild_colors()

    @property
    def lyrics_overlay(self) -> LyricsOverlay:
        return self._lyrics

    def set_lyrics(self, lines: list):
        self._lyrics.set_lyrics(lines)
        self._has_lyrics = bool(lines)

    def toggle_lyrics(self):
        self._lyrics_visible = not self._lyrics_visible
        if self._lyrics_visible:
            self._lyrics.show()
        else:
            self._lyrics.hide()
        return self._lyrics_visible

    def show_lyrics(self):
        self._lyrics_visible = True
        self._lyrics.show()

    def hide_lyrics(self):
        self._lyrics_visible = False
        self._lyrics.hide()

    @property
    def lyrics_visible(self) -> bool:
        return self._lyrics_visible

    def set_mode(self, mode: SpectrumMode):
        self._mode = mode

    def cycle_mode(self):
        self._mode = SpectrumMode((int(self._mode) + 1) % 3)

    def set_position_ratio(self, ratio: float):
        self._current_pos_ratio = ratio
        if self._spectrum_cache is not None:
            idx = int(ratio * (len(self._spectrum_cache) - 1))
            idx = max(0, min(idx, len(self._spectrum_cache) - 1))
            target = self._spectrum_cache[idx]
            self._levels += (target - self._levels) * self._animation_speed
            self._peaks = np.maximum(self._peaks * self._peak_decay, self._levels)

    def set_audio_data(self, spectrum_cache: np.ndarray, sample_rate: int):
        self._spectrum_cache = spectrum_cache
        self._sample_rate = sample_rate
        if spectrum_cache is not None and len(spectrum_cache) > 0:
            self._levels = spectrum_cache[0].copy()
            self._peaks = spectrum_cache[0].copy()
            self.update()

    def clear(self):
        self._levels = np.zeros(self.BAR_COUNT, dtype=np.float64)
        self._peaks = np.zeros(self.BAR_COUNT, dtype=np.float64)
        self._spectrum_cache = None
        self._lyrics.set_lyrics([])
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._lyrics.setGeometry(0, 0, self.width(), self.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_light = current_theme_mode() == "light"

        # When lyrics are visible, don't paint spectrum — mutually exclusive
        if self._lyrics_visible:
            bg = QColor("#f5f5f5") if is_light else QColor("#080810")
            painter.fillRect(self.rect(), bg)
            painter.end()
            return

        bg = QColor("#fafafa") if is_light else QColor("#0f0f1a")
        painter.fillRect(self.rect(), bg)

        if self._mode == SpectrumMode.Bars:
            self._paint_bars(painter)
        elif self._mode == SpectrumMode.Line:
            self._paint_line(painter)
        elif self._mode == SpectrumMode.Circular:
            self._paint_circular(painter)

        painter.end()

    def _paint_bars(self, painter: QPainter):
        w = self.width()
        h = self.height()
        bar_w = max(2, (w - 20) / self.BAR_COUNT - 2)
        gap = (w - 20) / self.BAR_COUNT

        for i in range(self.BAR_COUNT):
            level = self._levels[i]
            peak = self._peaks[i]
            bar_h = max(2, level * (h - 30))
            x = 10 + i * gap
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._bar_colors[i])
            painter.drawRoundedRect(QRectF(x, h - bar_h - 15, bar_w, bar_h), 2, 2)
            if peak > 0.01:
                peak_y = h - peak * (h - 30) - 15
                painter.setBrush(self._peak_color)
                painter.drawEllipse(QPointF(x + bar_w / 2, peak_y), 2.5, 2.5)

    def _paint_line(self, painter: QPainter):
        w = self.width()
        h = self.height()
        center_y = h / 2
        accent = current_accent()
        path = QPainterPath()
        step = (w - 40) / (self.BAR_COUNT - 1) if self.BAR_COUNT > 1 else 1
        for i in range(self.BAR_COUNT):
            x = 20 + i * step
            y = center_y - self._levels[i] * (center_y - 15)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        fill_path = QPainterPath(path)
        fill_path.lineTo(20 + (self.BAR_COUNT - 1) * step, center_y)
        fill_path.lineTo(20, center_y)
        fill_path.closeSubpath()
        grad = QLinearGradient(0, center_y, 0, 0)
        fill_top = QColor(accent)
        fill_top.setAlpha(120)
        fill_bottom = QColor(accent)
        fill_bottom.setAlpha(30)
        grad.setColorAt(0.0, fill_bottom)
        grad.setColorAt(1.0, fill_top)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawPath(fill_path)
        line_grad = QLinearGradient(20, 0, w - 20, 0)
        line_grad.setColorAt(0.0, accent)
        line_grad.setColorAt(0.5, QColor("#06b6d4"))
        line_grad.setColorAt(1.0, QColor("#ec4899"))
        painter.setPen(QPen(line_grad, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _paint_circular(self, painter: QPainter):
        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2
        radius = min(w, h) / 2 - 40
        for r_step in [0.25, 0.5, 0.75, 1.0]:
            r = radius * r_step
            painter.setPen(QPen(QColor(255, 255, 255, 10), 1))
            painter.drawEllipse(QPointF(cx, cy), r, r)
        angle_step = 360.0 / self.BAR_COUNT
        accent = current_accent()  # hoist — not per-bar
        for i in range(self.BAR_COUNT):
            angle = i * angle_step - 90
            rad = np.radians(angle)
            level = self._levels[i]
            inner_r = radius * 0.15
            bar_len = level * (radius - inner_r)
            bar_w = max(1.5, (2 * np.pi * radius / self.BAR_COUNT) * 0.5)
            start_x = cx + inner_r * np.cos(rad)
            start_y = cy + inner_r * np.sin(rad)
            end_x = cx + (inner_r + bar_len) * np.cos(rad)
            end_y = cy + (inner_r + bar_len) * np.sin(rad)
            t = i / self.BAR_COUNT
            r = int(accent.red() + t * (255 - accent.red()))
            g = int(accent.green() + t * (255 - accent.green()))
            b_val = int(accent.blue() + t * (255 - accent.blue()))
            painter.setPen(QPen(QColor(r, g, b_val, 220), bar_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(start_x, start_y), QPointF(end_x, end_y))
