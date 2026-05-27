from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (QPainter, QColor, QPen, QLinearGradient, QPainterPath,
                         QRadialGradient, QMouseEvent)
import numpy as np
import subprocess
import struct
from pathlib import Path
from audio_player.app import current_accent


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
        accent = current_accent()

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
    """Decode audio to F32LE mono 22.05kHz PCM. Tries gst-launch, then ffmpeg."""
    import shutil
    import os

    # Try GStreamer first
    gst_launch = shutil.which("gst-launch-1.0")
    if gst_launch:
        env = os.environ.copy()
        env["GST_REGISTRY_FORK_DISABLE"] = "1"
        env["GST_DEBUG"] = "1"
        gst_root = os.path.dirname(os.path.dirname(gst_launch))
        env["GST_PLUGIN_SCANNER"] = os.path.join(gst_root, "libexec", "gstreamer-1.0", "gst-plugin-scanner.exe")
        env["PATH"] = os.path.join(gst_root, "bin") + os.pathsep + env.get("PATH", "")
        try:
            import tempfile
            tmp_path = os.path.join(tempfile.gettempdir(),
                                    f"vbplayer_pcm_{os.path.basename(filepath)}.pcm")
            file_uri = filepath.replace("\\", "/")
            tmp_uri = tmp_path.replace("\\", "/")
            result = subprocess.run(
                [gst_launch, "-q",
                 "filesrc", f'location="{file_uri}"',
                 "!", "decodebin",
                 "!", "audioconvert",
                 "!", "audioresample",
                 "!", "audio/x-raw,format=F32LE,rate=22050,channels=1",
                 "!", "filesink", f'location="{tmp_uri}"'],
                capture_output=True, timeout=120, env=env,
            )
            if result.returncode == 0 and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
                with open(tmp_path, "rb") as f:
                    data = f.read()
                os.unlink(tmp_path)
                samples = np.frombuffer(data, dtype=np.float32)
                if len(samples) > 0:
                    return samples
            if result.stderr:
                import sys
                sys.stderr.write(f"[gst-launch] {result.stderr.decode(errors='ignore')[:500]}\n")
                sys.stderr.flush()
        except Exception:
            pass

    # Fall back to ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # Search common locations
        for p in [
            os.path.join("C:", os.sep, "msys64", "mingw64", "bin", "ffmpeg.exe"),
            os.path.join(os.environ.get("APPDATA", ""), "bilibili", "ffmpeg", "ffmpeg.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "bilibili", "ffmpeg", "ffmpeg.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "ffmpeg", "bin", "ffmpeg.exe"),
        ]:
            if os.path.isfile(p):
                ffmpeg = p
                break
    if ffmpeg:
        try:
            result = subprocess.run(
                [ffmpeg, "-i", filepath,
                 "-f", "f32le", "-ac", "1", "-ar", "22050",
                 "-loglevel", "quiet", "pipe:1"],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0 and len(result.stdout) > 0:
                samples = np.frombuffer(result.stdout, dtype=np.float32)
                if len(samples) > 0:
                    return samples
        except Exception:
            pass

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
