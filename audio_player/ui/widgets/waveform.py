from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QSettings
from PyQt6.QtGui import (QPainter, QColor, QPen, QLinearGradient, QPainterPath,
                         QRadialGradient, QMouseEvent)
import numpy as np
import subprocess
import struct
from pathlib import Path


def _accent_color() -> QColor:
    s = QSettings("VBPlayer", "VB Player")
    name = str(s.value("accent", "purple") or "purple")
    accents = {
        "purple": QColor("#7c3aed"),
        "blue":   QColor("#007AFF"),
        "green":  QColor("#10b981"),
        "orange": QColor("#f59e0b"),
        "pink":   QColor("#ec4899"),
        "red":    QColor("#ef4444"),
    }
    return accents.get(name, QColor("#7c3aed"))


class WaveformWidget(QWidget):
    seekRequested = pyqtSignal(float)  # ratio 0.0-1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.setMaximumHeight(70)
        self.setMouseTracking(True)
        self._waveform: np.ndarray | None = None
        self._position_ratio = 0.0
        self._hover_ratio = -1.0
        self._loading = False

    def load_audio(self, filepath: str):
        """Start async loading. For simplicity, we compute immediately."""
        self._loading = True
        self._waveform = None
        self.update()

        data = _compute_waveform(filepath)
        if data is not None:
            self._waveform = data
        self._loading = False
        self._position_ratio = 0.0
        self.update()

    def set_waveform_data(self, data: np.ndarray):
        """Accept pre-computed waveform from AudioAnalyzer."""
        if data is not None and len(data) > 0:
            self._waveform = data
            self._loading = False
            self.update()

    def set_position(self, ratio: float):
        self._position_ratio = max(0.0, min(1.0, ratio))
        self.update()

    def clear(self):
        self._waveform = None
        self._position_ratio = 0.0
        self.update()

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

        # Background
        painter.fillRect(self.rect(), QColor("#0f0f1a"))

        if self._loading:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Loading waveform...")
            painter.end()
            return

        if self._waveform is None or len(self._waveform) == 0:
            painter.end()
            return

        # Resample waveform data to match widget pixel width so progress aligns visually
        data = self._waveform
        num_bars = max(1, w)
        if len(data) != num_bars:
            indices = np.linspace(0, len(data) - 1, num_bars, dtype=int)
            data = data[indices]

        bar_w = 1.0
        played_idx = int(self._position_ratio * num_bars)
        accent = _accent_color()

        for i in range(num_bars):
            amp = data[i]
            bar_h = max(1, amp * (h - margin * 2) / 2)

            if i < played_idx:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent.lighter(100 + int(30 * i / num_bars)))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(37, 37, 64, 130))

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


def _decode_audio_to_pcm(filepath: str) -> np.ndarray | None:
    """Decode audio file to mono float32 PCM using GStreamer."""
    import shutil
    if not shutil.which("gst-launch-1.0"):
        return None
    try:
        result = subprocess.run(
            ["gst-launch-1.0", "-q",
             "filesrc", f"location={filepath}",
             "!", "decodebin",
             "!", "audioconvert",
             "!", "audioresample",
             "!", "audio/x-raw,format=F32LE,rate=22050,channels=1",
             "!", "fdsink"],
            capture_output=True, timeout=120
        )
        if result.returncode != 0 or len(result.stdout) == 0:
            return None
        samples = np.frombuffer(result.stdout, dtype=np.float32)
        return samples if len(samples) > 0 else None
    except Exception:
        return None


def _compute_waveform(filepath: str, num_bars: int = 2000) -> np.ndarray | None:
    """Decode audio to mono PCM and compute peak waveform."""
    try:
        samples = _decode_audio_to_pcm(filepath)
        if samples is None:
            return None

        # Downsample to num_bars by taking peak amplitude in each window
        window_size = max(1, len(samples) // num_bars)
        num_windows = len(samples) // window_size
        if num_windows < 2:
            return np.abs(samples[:num_bars])

        trimmed = samples[:num_windows * window_size]
        reshaped = trimmed.reshape(-1, window_size)
        peaks = np.max(np.abs(reshaped), axis=1)

        if len(peaks) != num_bars:
            indices = np.linspace(0, len(peaks) - 1, num_bars, dtype=int)
            peaks = peaks[indices]

        max_val = np.max(peaks)
        if max_val > 0:
            peaks = peaks / max_val
        peaks = np.power(peaks, 0.65)

        return peaks.astype(np.float64)
    except Exception:
        return None
