from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPen, QMouseEvent)
import numpy as np
from audio_player.app import current_accent, current_theme_mode


class WaveformWidget(QWidget):
    seekRequested = pyqtSignal(float)  # ratio 0.0-1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.setMaximumHeight(70)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("")
        self.setMouseTracking(True)
        self._waveform: np.ndarray | None = None
        self._resampled: np.ndarray | None = None  # cached at display resolution
        self._resampled_width: int = 0
        self._position_ratio = 0.0
        self._hover_ratio = -1.0
        self._loading = False

    def set_waveform_data(self, data: np.ndarray):
        """Accept pre-computed waveform from AudioAnalyzer."""
        if data is not None and len(data) > 0:
            self._waveform = data
            self._loading = False
            self._resampled = None  # invalidate cache
            self.update()

    def set_position(self, ratio: float):
        self._position_ratio = max(0.0, min(1.0, ratio))
        self.update()

    def clear(self):
        self._waveform = None
        self._resampled = None
        self._position_ratio = 0.0
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resampled = None  # width changed → invalidate resample cache

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._waveform is not None:
            ratio = event.position().x() / self.width()
            self.seekRequested.emit(max(0.0, min(1.0, ratio)))

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._waveform is not None:
            self._hover_ratio = event.position().x() / self.width()
            self.update()

    def leaveEvent(self, event):
        self._hover_ratio = -1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        center_y = h / 2
        margin = 4

        # Background — follow theme
        is_light = current_theme_mode() == "light"
        bg = QColor("#f8f8f8") if is_light else QColor("#1e1e1e")
        painter.fillRect(self.rect(), bg)

        if self._loading:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Loading waveform...")
            painter.end()
            return

        if self._waveform is None or len(self._waveform) == 0:
            painter.end()
            return

        # Use cached resample — only recompute when width changes or data changes
        num_bars = max(1, w)
        if self._resampled is None or self._resampled_width != num_bars:
            if len(self._waveform) != num_bars:
                indices = np.linspace(0, len(self._waveform) - 1, num_bars, dtype=int)
                self._resampled = self._waveform[indices]
            else:
                self._resampled = self._waveform
            self._resampled_width = num_bars
        data = self._resampled

        bar_w = 1.0
        played_idx = int(self._position_ratio * num_bars)
        accent = current_accent()
        accent_played = accent.lighter(115)  # single shared color for played region
        unplayed_color = QColor(37, 37, 64, 130)  # cached — build once

        for i in range(num_bars):
            amp = data[i]
            bar_h = max(1, amp * (h - margin * 2) / 2)

            if i < played_idx:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent_played)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(unplayed_color)

            rect = QRectF(i, center_y - bar_h, bar_w, bar_h * 2)
            painter.drawRect(rect)

        # Hover indicator
        if 0 <= self._hover_ratio <= 1:
            hx = self._hover_ratio * w
            painter.setPen(QPen(accent.lighter(130), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(hx, 0), QPointF(hx, h))

        # Position line
        px = self._position_ratio * w
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawLine(QPointF(px, margin), QPointF(px, h - margin))

        painter.end()
