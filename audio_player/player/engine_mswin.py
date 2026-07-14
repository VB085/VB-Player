"""MSVC Python audio engine — ffmpeg decode + sounddevice/asio_ctypes output.

Zero GStreamer dependency. Works on standard Windows Python 3.12+.
"""
import subprocess, threading, time, os, sys, math, struct
from collections import deque
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_player.player._types import PlaybackState
from audio_player.i18n import _
from audio_player.platform.windows import asio_ctypes

# ── Decoder ──────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str | None:
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg: return ffmpeg
    for p in [Path("C:/msys64/mingw64/bin/ffmpeg.exe"),
              Path(os.environ.get("APPDATA", "")) / "bilibili/ffmpeg/ffmpeg.exe"]:
        if p.is_file(): return str(p)
    return None


class MSAudioEngine(QObject):
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    stateChanged = pyqtSignal(int)
    trackChanged = pyqtSignal(str)
    trackFinished = pyqtSignal()
    errorOccurred = pyqtSignal(str)
    volumeChanged = pyqtSignal(float)
    exclusiveModeChanged = pyqtSignal(bool)
    outputInfoChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_file = ""
        self._app_state = PlaybackState.Stopped
        self._position_ms = 0
        self._duration_ms = 0
        self._volume_level = 0.8
        self._pipeline_sample_rate = 0
        self._source_is_dsd = False
        self._dsd_decode_mode = "pcm"
        self._exclusive_mode = False
        self._exclusive_device = ""
        self._asio_sample_type = "auto"
        self._gapless_enabled = False
        self._replaygain_enabled = False
        self._eq_enabled = False
        self._eq_gains = [0.0] * 10
        self._is_stream = False

        # Runtime state
        self._ffmpeg_proc = None
        self._output_thread = None
        self._stop_event = threading.Event()
        self._ring = deque()
        self._ring_lock = threading.Lock()
        self._total_bytes_read = 0
        self._seek_offset_bytes = 0

        # WASAPI
        self._sd_stream = None

        # ASIO
        self._asio_dev = None
        self._asio_feed_timer = None

        # Poll timer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll)

        self._load_settings()

    def _load_settings(self):
        from PyQt6.QtCore import QSettings
        s = QSettings("VBPlayer", "VB Player")
        self._exclusive_mode = str(s.value("exclusive_mode", "false")).lower() == "true"
        self._exclusive_device = str(s.value("exclusive_device", "") or "")
        self._dsd_decode_mode = str(s.value("dsd_mode", "pcm") or "pcm")
        self._asio_sample_type = str(s.value("asio_sample_type", "auto") or "auto")
        self._volume_level = float(s.value("volume", 0.8) or 0.8)

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def volume(self) -> float: return self._volume_level

    @volume.setter
    def volume(self, v: float):
        self._volume_level = max(0.0, min(1.0, v))
        self.volumeChanged.emit(self._volume_level)

    @property
    def position(self) -> int: return self._position_ms

    @property
    def duration(self) -> int: return self._duration_ms

    @property
    def current_file(self) -> str: return self._current_file

    @property
    def is_playing(self) -> bool: return self._app_state == PlaybackState.Playing

    @property
    def exclusive_mode(self) -> bool: return self._exclusive_mode

    @exclusive_mode.setter
    def exclusive_mode(self, v: bool):
        self._exclusive_mode = v
        self.exclusiveModeChanged.emit(v)

    @property
    def exclusive_device(self) -> str: return self._exclusive_device

    @exclusive_device.setter
    def exclusive_device(self, d: str): self._exclusive_device = d

    @property
    def dsd_mode(self) -> str: return self._dsd_decode_mode

    @dsd_mode.setter
    def dsd_mode(self, m: str): self._dsd_decode_mode = m

    @property
    def asio_sample_type(self) -> str: return self._asio_sample_type

    @asio_sample_type.setter
    def asio_sample_type(self, v: str): self._asio_sample_type = v

    @property
    def output_info(self) -> dict:
        return {"name": "MSWin Audio", "driver": "ffmpeg+sounddevice",
                "mode": "Exclusive" if self._exclusive_mode else "Shared",
                "sample_rate": self._pipeline_sample_rate,
                "is_exclusive": self._exclusive_mode, "api": "mswin"}

    # ── ffmpeg pipeline ──────────────────────────────────────────────────

    def _start_ffmpeg(self, filepath: str, seek_ms: int = 0):
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            self.errorOccurred.emit("ffmpeg not found")
            return False

        from audio_player.player.metadata import read_metadata
        try:
            meta = read_metadata(filepath)
            rate = meta.sample_rate if meta.sample_rate > 0 else 44100
            self._duration_ms = int(meta.duration_seconds * 1000) if meta.duration_seconds > 0 else 0
        except Exception:
            rate = 44100; self._duration_ms = 0

        ext = Path(filepath).suffix.lower()
        if ext in (".dsf", ".dff"): rate = 88200
        self._pipeline_sample_rate = rate
        self._source_is_dsd = ext in (".dsf", ".dff")

        if self._duration_ms > 0:
            self.durationChanged.emit(self._duration_ms)

        cmd = [ffmpeg, "-nostdin", "-i", filepath,
               "-f", "f32le", "-ar", str(rate), "-ac", "2", "-loglevel", "error", "pipe:1"]
        if seek_ms > 0:
            cmd.insert(2, "-ss"); cmd.insert(3, f"{seek_ms/1000:.3f}")

        try:
            self._ffmpeg_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as e:
            self.errorOccurred.emit(f"ffmpeg: {e}")
            return False

        self._total_bytes_read = 0
        self._seek_offset_bytes = int(seek_ms * rate * 2 * 4 / 1000)
        return True

    def _read_ffmpeg_loop(self):
        """Background thread: read ffmpeg stdout → ring buffer (WASAPI) or asio_write (ASIO)."""
        chunk = 65536
        while not self._stop_event.is_set() and self._ffmpeg_proc is not None:
            try:
                data = self._ffmpeg_proc.stdout.read(chunk)
            except Exception:
                break
            if not data:
                break  # EOF

            self._total_bytes_read += len(data)

            if getattr(self, '_asio_worker', None) is not None:
                try:
                    self._asio_worker.stdin.write(data)
                    self._asio_worker.stdin.flush()
                except (BrokenPipeError, OSError):
                    break
            elif self._asio_dev is not None:
                self._asio_dev.write(data)
            else:
                with self._ring_lock:
                    self._ring.append(data)

            # ASIO: track position from bytes written (wasapi uses callback)
            if getattr(self, '_asio_worker', None) is not None or self._asio_dev is not None:
                total_bytes = self._seek_offset_bytes + self._total_bytes_read
                rate = self._pipeline_sample_rate or 44100
                pos_ms = int(total_bytes / (rate * 2 * 4) * 1000)
                if abs(pos_ms - self._position_ms) > 100:
                    self._position_ms = pos_ms
                    self.positionChanged.emit(pos_ms)
        if not self._stop_event.is_set():
            self.trackFinished.emit()

    # ── Public API ──────────────────────────────────────────────────────

    def load(self, filepath: str):
        self.stop()
        self._current_file = filepath
        self._position_ms = 0
        self.trackChanged.emit(filepath)

    def play(self):
        if not self._current_file:
            return
        if self._app_state == PlaybackState.Paused:
            self._app_state = PlaybackState.Playing
            self.stateChanged.emit(PlaybackState.Playing)
            if self._asio_feed_timer:
                self._asio_feed_timer.start()
            self._poll_timer.start()
            return

        self.stop()
        is_asio = self._exclusive_mode and self._exclusive_device.startswith("asio:")
        if not is_asio:
            if not self._start_ffmpeg(self._current_file):
                return
        else:
            # ASIO: read metadata for duration
            from audio_player.player.metadata import read_metadata
            try:
                meta = read_metadata(self._current_file)
                rate = meta.sample_rate if meta.sample_rate > 0 else 44100
                self._duration_ms = int(meta.duration_seconds * 1000) if meta.duration_seconds > 0 else 0
                self._pipeline_sample_rate = rate
                if self._duration_ms > 0:
                    self.durationChanged.emit(self._duration_ms)
            except Exception:
                self._pipeline_sample_rate = 44100

        # Clear ring buffer
        with self._ring_lock:
            self._ring.clear()

        # Start output
        self._stop_event.clear()
        if self._exclusive_mode and self._exclusive_device.startswith("asio:"):
            self._start_asio(self._current_file)
        else:
            self._start_wasapi()

        # Start feed thread (WASAPI only — ASIO uses shell pipe)
        if not (self._exclusive_mode and self._exclusive_device.startswith("asio:")):
            self._output_thread = threading.Thread(target=self._read_ffmpeg_loop, daemon=True)
            self._output_thread.start()

        self._play_start_time = time.time()
        self._app_state = PlaybackState.Playing
        self.stateChanged.emit(PlaybackState.Playing)
        self._poll_timer.start()

    def pause(self):
        if self._app_state != PlaybackState.Playing:
            return
        self._stop_event.set()
        self._app_state = PlaybackState.Paused
        self.stateChanged.emit(PlaybackState.Paused)
        self._poll_timer.stop()
        if self._asio_feed_timer:
            self._asio_feed_timer.stop()

    def stop(self):
        self._stop_event.set()
        if self._sd_stream is not None:
            try: self._sd_stream.stop(); self._sd_stream.close()
            except Exception: pass
            self._sd_stream = None
        if getattr(self, '_asio_pipe', None) is not None:
            try: self._asio_pipe.kill(); self._asio_pipe.wait(timeout=3)
            except Exception: pass
            self._asio_pipe = None
        if getattr(self, '_asio_worker', None) is not None:
            try:
                self._asio_worker.stdin.close()
                self._asio_worker.wait(timeout=3)
            except Exception: pass
            self._asio_worker = None
        if self._asio_dev is not None:
            try: self._asio_dev.close()
            except Exception: pass
            self._asio_dev = None
        if self._asio_feed_timer:
            self._asio_feed_timer.stop(); self._asio_feed_timer = None
        if self._ffmpeg_proc:
            try: self._ffmpeg_proc.kill(); self._ffmpeg_proc.wait(timeout=3)
            except Exception: pass
            self._ffmpeg_proc = None
        self._position_ms = 0
        self._app_state = PlaybackState.Stopped
        self.stateChanged.emit(PlaybackState.Stopped)
        self._poll_timer.stop()

    def toggle(self):
        if self._app_state == PlaybackState.Playing:
            self.pause()
        else:
            self.play()

    def seek(self, position_ms: int):
        if not self._current_file:
            return
        was_playing = self._app_state == PlaybackState.Playing
        self._stop_event.set()
        if self._ffmpeg_proc:
            try: self._ffmpeg_proc.kill(); self._ffmpeg_proc.wait(timeout=2)
            except Exception: pass
            self._ffmpeg_proc = None
        if self._sd_stream:
            try: self._sd_stream.stop(); self._sd_stream.close()
            except Exception: pass
            self._sd_stream = None
        if not self._start_ffmpeg(self._current_file, seek_ms=position_ms):
            return
        with self._ring_lock:
            self._ring.clear()
        self._stop_event.clear()
        if self._exclusive_device.startswith("asio:"):
            self._start_asio()
        else:
            self._start_wasapi()
        self._output_thread = threading.Thread(target=self._read_ffmpeg_loop, daemon=True)
        self._output_thread.start()
        if was_playing:
            self._app_state = PlaybackState.Playing
            self._poll_timer.start()

    def seek_ratio(self, ratio: float):
        self.seek(int(ratio * self._duration_ms))

    # ── WASAPI output ───────────────────────────────────────────────────

    def _start_wasapi(self):
        import sounddevice as sd
        import numpy as np

        rate = self._pipeline_sample_rate or 44100
        bs = 1024  # frames per callback
        ring_lock = self._ring_lock
        ring = self._ring
        volume_ref = self  # to read self._volume_level

        _frames_played = [0]
        _rate = rate

        def _callback(outdata, frames, _time, status):
            if status:
                print(f"[wasapi] {status}", file=sys.stderr)
            with ring_lock:
                needed = frames * 2
                buf = np.empty(needed, dtype=np.float32)
                filled = 0
                while filled < needed and ring:
                    chunk_data = ring.popleft()
                    chunk_floats = np.frombuffer(chunk_data, dtype=np.float32)
                    remaining = needed - filled
                    take = min(len(chunk_floats), remaining)
                    buf[filled:filled+take] = chunk_floats[:take]
                    filled += take
                    if take < len(chunk_floats):
                        ring.appendleft(chunk_floats[take:].tobytes())
                if filled < needed:
                    buf[filled:] = 0.0
                outdata[:, 0] = buf[0::2] * volume_ref._volume_level
                outdata[:, 1] = buf[1::2] * volume_ref._volume_level
            _frames_played[0] += frames
            # Update position every ~100ms
            if _frames_played[0] % (_rate // 10) < frames:
                pos_ms = int(_frames_played[0] / _rate * 1000)
                if abs(pos_ms - volume_ref._position_ms) > 100:
                    volume_ref._position_ms = pos_ms
                    volume_ref.positionChanged.emit(pos_ms)

        try:
            self._sd_stream = sd.OutputStream(
                samplerate=rate, channels=2, callback=_callback,
                blocksize=bs, dtype='float32')
            self._sd_stream.start()
        except Exception as e:
            self.errorOccurred.emit(f"WASAPI: {e}")

    # ── ASIO output (via shell pipe: ffmpeg | asio_worker) ─────────────

    def _start_asio(self, filepath: str, seek_ms: int = 0):
        clsid = self._exclusive_device[5:]
        rate = self._pipeline_sample_rate or 44100
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            self.errorOccurred.emit("ffmpeg not found")
            return
        worker_path = Path(__file__).resolve().parent.parent / "platform/windows/asio_worker.py"
        if not worker_path.exists():
            self.errorOccurred.emit("asio_worker.py not found")
            return

        # Build shell pipeline: ffmpeg | python asio_worker.py
        # OS pipes handle all I/O — zero Python GIL involvement in data path
        ffmpeg_cmd = f'"{ffmpeg}" -nostdin -i "{filepath}" -f f32le -ar {rate} -ac 2 -loglevel error pipe:1'
        if seek_ms > 0:
            ffmpeg_cmd = f'"{ffmpeg}" -nostdin -ss {seek_ms/1000:.3f} -i "{filepath}" -f f32le -ar {rate} -ac 2 -loglevel error pipe:1'
        worker_cmd = f'"{sys.executable}" "{worker_path}" {clsid} {rate}'
        shell_cmd = f'{ffmpeg_cmd} | {worker_cmd}'
        import sys as _sys
        try:
            self._asio_pipe = subprocess.Popen(
                shell_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception as e:
            self.errorOccurred.emit(f"ASIO pipe: {e}")
            return

    # ── Poll ─────────────────────────────────────────────────────────────

    def _poll(self):
        if self._app_state != PlaybackState.Playing:
            return
        if getattr(self, '_asio_pipe', None) is not None:
            # ASIO shell pipe: estimate position from elapsed real time
            if not hasattr(self, '_play_start_time'):
                self._play_start_time = time.time()
            elapsed_ms = int((time.time() - self._play_start_time) * 1000)
            pos_ms = self._seek_offset_ms + elapsed_ms
            if pos_ms > self._duration_ms > 0:
                pos_ms = self._duration_ms
            if abs(pos_ms - self._position_ms) > 100:
                self._position_ms = pos_ms
                self.positionChanged.emit(pos_ms)
        else:
            rate = self._pipeline_sample_rate or 44100
            total_bytes = self._seek_offset_bytes + self._total_bytes_read
            pos_ms = int(total_bytes / (rate * 2 * 4) * 1000)
            if abs(pos_ms - self._position_ms) > 100:
                self._position_ms = pos_ms
                self.positionChanged.emit(pos_ms)
