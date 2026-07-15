"""MSVC Python audio engine — ffmpeg decode + sounddevice/asio_ctypes output.

Zero GStreamer dependency. Works on standard Windows Python 3.12+.
"""
import subprocess, threading, time, os, sys, math, struct, ctypes
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
        import sys as _s; _s.stderr.write("[engine] MSVC ffmpeg+sounddevice engine loaded\n")
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
        self._ring_max = 10  # ~1.8s buffer, smaller = less GIL contention
        self._total_bytes_read = 0
        self._seek_offset_bytes = 0
        self._seek_offset_ms = 0
        self._play_start_time = 0

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
        self._volume_level = float(max(0.0, min(1.0, v)))
    def set_volume(self, v: float):
        self._volume_level = float(max(0.0, min(1.0, v)))

    @property
    def position(self) -> int: return self._position_ms

    @property
    def duration(self) -> int: return self._duration_ms

    @property
    def current_file(self) -> str: return self._current_file

    @property
    def is_playing(self) -> bool: return self._app_state == PlaybackState.Playing

    @property
    def gapless_enabled(self) -> bool: return self._gapless_enabled

    @gapless_enabled.setter
    def gapless_enabled(self, v: bool): self._gapless_enabled = v

    @property
    def replaygain_enabled(self) -> bool: return self._replaygain_enabled

    @replaygain_enabled.setter
    def replaygain_enabled(self, v: bool): self._replaygain_enabled = v

    def set_volume(self, v: float):
        self._volume_level = max(0.0, min(1.0, v))

    def set_eq_gain(self, band: int, gain: float):
        if 0 <= band < len(self._eq_gains):
            self._eq_gains[band] = gain

    def set_eq_band_gain(self, band_idx: int, db: float):
        """Compatibility with GStreamer engine API."""
        self.set_eq_gain(band_idx, db)

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
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.errorOccurred.emit(f"ffmpeg: {e}")
            return False

        self._total_bytes_read = 0
        self._seek_offset_bytes = int(seek_ms * rate * 2 * 4 / 1000)
        return True

    # ── Public API ──────────────────────────────────────────────────────

    def load(self, filepath: str):
        self.stop()
        self._current_file = filepath
        self._position_ms = 0
        # Read metadata for duration and sample rate
        try:
            from audio_player.player.metadata import read_metadata
            meta = read_metadata(filepath)
            self._pipeline_sample_rate = meta.sample_rate if meta.sample_rate > 0 else 44100
            self._duration_ms = int(meta.duration_seconds * 1000) if meta.duration_seconds > 0 else 0
            self._source_is_dsd = Path(filepath).suffix.lower() in ('.dsf', '.dff')
            if self._duration_ms > 0:
                self.durationChanged.emit(self._duration_ms)
        except Exception:
            self._pipeline_sample_rate = 44100; self._duration_ms = 0
        self.trackChanged.emit(filepath)

    def play(self):
        if not self._current_file:
            return
        if self._app_state == PlaybackState.Paused:
            self._app_state = PlaybackState.Playing
            self.stateChanged.emit(PlaybackState.Playing)
            resume_ms = getattr(self, '_pause_position_ms', 0)
            if self._asio_dev is not None:
                # ASIO resume: re-create pipeline at paused position
                try: self._asio_dev.close()
                except Exception: pass
                self._asio_dev = None
                self._seek_offset_ms = resume_ms
                self._play_start_time = time.time()
                self._asio_last_rpos = 0
                self._asio_total_frames = resume_ms * (self._pipeline_sample_rate or 44100) // 1000
                self._stop_event.clear()
                self._start_asio(self._current_file, seek_ms=resume_ms)
            elif self._current_file:
                # WASAPI resume: re-create ffmpeg + feed at paused position
                self._seek_offset_ms = resume_ms
                self._seek_offset_bytes = int(resume_ms * (self._pipeline_sample_rate or 44100) * 2 * 4 / 1000)
                self._total_bytes_read = 0
                if self._start_ffmpeg(self._current_file, seek_ms=resume_ms):
                    self._sd_stream = None
                    self._stop_event.clear()
                    self._start_wasapi()
                    self._output_thread = threading.Thread(target=self._wasapi_loop, daemon=True)
                    self._output_thread.start()
            self._play_start_time = time.time()
            self._poll_timer.start()
            return

        self.stop()
        self._seek_offset_ms = 0
        self._play_start_time = time.time()
        self._asio_last_rpos = 0
        self._asio_total_frames = 0
        is_asio = self._exclusive_mode and self._exclusive_device.startswith("asio:")
        if not is_asio:
            if not self._start_ffmpeg(self._current_file):
                return

        # Clear ring buffer
        with self._ring_lock:
            self._ring.clear()

        # Start output
        self._stop_event.clear()
        if self._exclusive_mode and self._exclusive_device.startswith("asio:"):
            self._start_asio(self._current_file)
        else:
            self._start_wasapi()

        # Start WASAPI feed/playback loop (single thread, blocking write)
        if not (self._exclusive_mode and self._exclusive_device.startswith("asio:")):
            self._output_thread = threading.Thread(target=self._wasapi_loop, daemon=True)
            self._output_thread.start()

        self._play_start_time = time.time()
        self._app_state = PlaybackState.Playing
        self.stateChanged.emit(PlaybackState.Playing)
        self._poll_timer.start()

    def pause(self):
        if self._app_state != PlaybackState.Playing:
            return
        # Signal stop FIRST so feed threads don't emit trackFinished
        self._stop_event.set()
        # Stop WASAPI output immediately
        if self._sd_stream is not None:
            try: self._sd_stream.abort(); self._sd_stream.close()
            except Exception: pass
            self._sd_stream = None
        # Then kill ffmpeg — pipes close, threads unblock from os.read()
        if self._ffmpeg_proc is not None:
            try: self._ffmpeg_proc.kill()
            except Exception: pass
            self._ffmpeg_proc = None
        for evt in getattr(self, '_feed_stops', []):
            evt.set()
        self._feed_stops = []
        self._pause_position_ms = self._position_ms
        if self._asio_dev is not None:
            try:
                vt = ctypes.cast(self._asio_dev._ptr, ctypes.POINTER(ctypes.c_void_p))[0]
                V = lambda i,r,*a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(
                    ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value)
                V(8, ctypes.c_long)(self._asio_dev._ptr)
                self._asio_dev._running = False
            except Exception:
                pass
        self._app_state = PlaybackState.Paused
        self.stateChanged.emit(PlaybackState.Paused)
        self._poll_timer.stop()

    def stop(self):
        self._stop_event.set()
        # Signal all per-feed stop events first — threads will exit
        for evt in getattr(self, '_feed_stops', []):
            evt.set()
        self._feed_stops = []
        # Kill ffmpeg first (stops data flow)
        if self._ffmpeg_proc is not None:
            try: self._ffmpeg_proc.kill()
            except Exception: pass
            self._ffmpeg_proc = None
        if self._sd_stream is not None:
            try: self._sd_stream.stop(); self._sd_stream.close()
            except Exception: pass
            self._sd_stream = None
        # ASIO: close with brief timeout — callback may hold GIL
        if self._asio_dev is not None:
            dev = self._asio_dev; self._asio_dev = None
            try:
                import threading as _th
                closed = [False]
                def _do_close():
                    try: dev.close()
                    except Exception: pass
                    closed[0] = True
                t = _th.Thread(target=_do_close, daemon=True)
                t.start()
                t.join(timeout=0.5)
                if not closed[0]:
                    import sys as _s
                    _s.stderr.write("[engine] ASIO close timed out, forcing\n")
                    _s.stderr.flush()
            except Exception:
                pass
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
        if getattr(self, '_asio_worker', None) is not None:
            try: self._asio_worker.kill(); self._asio_worker.wait(timeout=3)
            except Exception: pass
            self._asio_worker = None
        if getattr(self, '_ffmpeg_proc', None) is not None:
            try: self._ffmpeg_proc.kill(); self._ffmpeg_proc.wait(timeout=3)
            except Exception: pass
            self._ffmpeg_proc = None

        with self._ring_lock:
            self._ring.clear()
        self._stop_event.clear()

        is_asio = self._exclusive_device.startswith("asio:")
        if is_asio:
            self._seek_offset_ms = position_ms
            self._play_start_time = time.time()
            self._start_asio(self._current_file, seek_ms=position_ms)
        else:
            if not self._start_ffmpeg(self._current_file, seek_ms=position_ms):
                return
            self._start_wasapi()
            self._output_thread = threading.Thread(target=self._wasapi_loop, daemon=True)
            self._output_thread.start()

        if was_playing:
            self._app_state = PlaybackState.Playing
            self._poll_timer.start()

    def seek_ratio(self, ratio: float):
        self.seek(int(ratio * self._duration_ms))

    # ── WASAPI output (blocking write — C-level wait, zero GIL) ───────

    def _start_wasapi(self):
        import sounddevice as sd
        rate = self._pipeline_sample_rate or 44100
        bs = 1024
        ring_lock = self._ring_lock
        ring = self._ring
        volume_ref = self

        def _callback(outdata, frames, _time, status):
            if status:
                print(f"[wasapi] {status}", file=sys.stderr)
            vol = volume_ref._volume_level
            filled = 0
            with ring_lock:
                while filled < frames and ring:
                    chunk = ring.popleft()
                    nf = len(chunk) // 2
                    take = min(nf, frames - filled)
                    ts = take * 2
                    outdata[filled:filled+take, 0] = chunk[0:ts:2] * vol
                    outdata[filled:filled+take, 1] = chunk[1:ts:2] * vol
                    filled += take
                    if take < nf:
                        ring.appendleft(chunk[ts:])
            if filled < frames:
                outdata[filled:, :] = 0.0
            _cb_frames[0] += frames
            pos_ms = int(_cb_frames[0] / _rate * 1000) + volume_ref._seek_offset_ms
            if pos_ms != volume_ref._position_ms:
                volume_ref._position_ms = pos_ms
                volume_ref.positionChanged.emit(pos_ms)

        _cb_frames = [0]
        _rate = rate
        try:
            self._sd_stream = sd.OutputStream(
                samplerate=rate, channels=2, callback=_callback,
                blocksize=bs, dtype='float32')
            self._sd_stream.start()
        except Exception as e:
            self.errorOccurred.emit(f"WASAPI: {e}")

    def _wasapi_loop(self):
        """Feed thread: read ffmpeg → ring. Callback handles output."""
        import os as _os, numpy as _np
        fd = self._ffmpeg_proc.stdout.fileno()
        ring = self._ring
        ring_lock = self._ring_lock
        pending = b''
        data = b'x'

        _frames_written = 0
        rate = self._pipeline_sample_rate or 44100

        while not self._stop_event.is_set():
            if len(ring) < self._ring_max:
                try:
                    data = _os.read(fd, 65536)
                except Exception:
                    break
                if data:
                    pending += data
            frame_bytes = 8
            complete = (len(pending) // frame_bytes) * frame_bytes
            if complete > 0:
                arr = _np.frombuffer(pending[:complete], dtype=_np.float32).copy()
                pending = pending[complete:]
                with ring_lock:
                    ring.append(arr)
                time.sleep(0)  # yield after each append
            else:
                time.sleep(0.05)  # ring full — long sleep, free GIL for Qt
            if not data and len(pending) == 0 and not ring:
                break

        if not self._stop_event.is_set():
            self.trackFinished.emit()

    # ── ASIO output (asio_ctypes directly) ────────────────────────────

    def _start_asio(self, filepath: str, seek_ms: int = 0):
        clsid = self._exclusive_device[5:]
        rate = self._pipeline_sample_rate or 44100
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            self.errorOccurred.emit("ffmpeg not found")
            return

        try:
            self._asio_dev = asio_ctypes.ASIODevice(clsid, rate)
        except Exception as e:
            self.errorOccurred.emit(f"ASIO open: {e}")
            return

        ffmpeg_args = [ffmpeg, "-nostdin", "-i", filepath,
                       "-f", "f32le", "-ar", str(rate), "-ac", "2",
                       "-loglevel", "error", "pipe:1"]
        if seek_ms > 0:
            ffmpeg_args = [ffmpeg, "-nostdin", "-ss", f"{seek_ms/1000:.3f}",
                           "-i", filepath,
                           "-f", "f32le", "-ar", str(rate), "-ac", "2",
                           "-loglevel", "error", "pipe:1"]

        try:
            self._ffmpeg_proc = subprocess.Popen(
                ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._asio_dev.close(); self._asio_dev = None
            self.errorOccurred.emit(f"ffmpeg: {e}")
            return

        dev = self._asio_dev
        proc = self._ffmpeg_proc
        _rate = rate
        # Per-feed stop signal — prevents old feeds reviving after stop_event clear
        feed_stop = threading.Event()
        if hasattr(self, '_feed_stops'):
            self._feed_stops.append(feed_stop)
        else:
            self._feed_stops = [feed_stop]

        def _feed():
            import os as _os
            fd2 = proc.stdout.fileno()
            fed = 0
            # Pre-buffer ~0.3s async in feed thread (doesn't block UI)
            prefill_target = dev._buffer_size * 25
            while fed < prefill_target * 8 and not feed_stop.is_set():
                try:
                    d = _os.read(fd2, 65536)
                except Exception:
                    break
                if not d:
                    break
                dev.write(d)
                fed += len(d)
            RING = 262144
            BS = dev._buffer_size
            rpos = dev._rpos_cell
            while not feed_stop.is_set():
                used = (dev._wpos - rpos[0]) % RING
                free = RING - used
                # Wait if ring too full or write would wrap past end
                if free < BS * 8:
                    time.sleep(0.05)
                    continue
                # Don't let write wrap — only write contiguous space at tail
                tail_space = RING - dev._wpos
                max_ns = min(free - BS * 4, tail_space)
                if max_ns <= 0:
                    time.sleep(0.05)
                    continue
                try:
                    data = _os.read(fd2, min(max_ns * 8, 65536))
                except Exception:
                    break
                if not data:
                    break  # ffmpeg EOF
                # Process only complete stereo frames
                frame_bytes = 8
                complete = (len(data) // frame_bytes) * frame_bytes
                if complete == 0:
                    continue
                dev.write(data[:complete])
                fed += complete
                time.sleep(0.002)  # yield GIL to Qt UI thread
            # Wait for ring to drain before emitting trackFinished
            while not feed_stop.is_set() and dev._wpos != rpos[0]:
                time.sleep(0.05)
            if not feed_stop.is_set() and fed > 0:
                self.trackFinished.emit()
            elif not feed_stop.is_set():
                self.errorOccurred.emit("ASIO: ffmpeg failed to decode")

        self._output_thread = threading.Thread(target=_feed, daemon=True)
        self._output_thread.start()

    # ── Poll ─────────────────────────────────────────────────────────────

    def _poll(self):
        if self._app_state != PlaybackState.Playing:
            return
        if getattr(self, '_asio_dev', None) is not None and self._asio_dev._running:
            # ASIO: track total consumed frames via rpos wrap detection
            rpos = self._asio_dev._rpos_cell[0]
            if not hasattr(self, '_asio_last_rpos'):
                self._asio_last_rpos = rpos
                self._asio_total_frames = 0
            # Detect wrap: rpos jumped backwards
            RING = 262144
            prev = self._asio_last_rpos
            if rpos < prev:
                self._asio_total_frames += (RING - prev) + rpos
            else:
                self._asio_total_frames += rpos - prev
            self._asio_last_rpos = rpos
            rate = self._pipeline_sample_rate or 44100
            pos_ms = int(self._asio_total_frames / rate * 1000)
            if pos_ms > self._duration_ms > 0:
                pos_ms = self._duration_ms
            if abs(pos_ms - self._position_ms) > 30:
                self._position_ms = pos_ms
                self.positionChanged.emit(pos_ms)
        elif self._sd_stream is not None:
            pass  # WASAPI position emitted by callback (actual playback pos)
