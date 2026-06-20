from PyQt6.QtCore import QObject, QThread, pyqtSignal
import numpy as np
from dataclasses import dataclass


@dataclass
class LyricsLine:
    time_ms: int
    text: str
    translation: str = ""  # paired bilingual translation line


class _DecoderWorker(QThread):
    finished = pyqtSignal(object, object, object)  # waveform, spectrum, lyrics

    def __init__(self, filepath: str, parent=None, bins: int = 64, snapshots_per_sec: int = 30):
        super().__init__(parent)
        self._filepath = filepath
        self._bins = bins
        self._snapshots_per_sec = snapshots_per_sec

    def run(self):
        waveform = None
        spectrum = None
        lyrics = []
        try:
            samples = self._decode_to_pcm()
            if samples is not None and len(samples) > 0:
                waveform = self._compute_waveform(samples)
                spectrum = self._compute_spectrum(samples, self._bins, self._snapshots_per_sec)
            lyrics = self._load_lyrics()
        except Exception:
            import traceback, sys
            traceback.print_exc(file=sys.stderr)
        self.finished.emit(waveform, spectrum, lyrics)

    def _decode_to_pcm(self) -> np.ndarray | None:
        """Decode audio to F32LE mono 22.05kHz PCM.

        Tries gst-launch first, falls back to ffmpeg on failure.
        """
        samples = self._decode_via_gst()
        if samples is not None:
            return samples
        return self._decode_via_ffmpeg()

    def _decode_via_gst(self) -> np.ndarray | None:
        import subprocess
        import shutil
        import os

        gst_launch = shutil.which("gst-launch-1.0")
        gst_root = None
        if not gst_launch:
            for root_var in ("GSTREAMER_1_0_ROOT_MSVC_X86_64",
                             "GSTREAMER_1_0_ROOT_X86_64",
                             "GSTREAMER_1_0_ROOT_MINGW_X86_64"):
                root = os.environ.get(root_var, "")
                if root:
                    candidate = os.path.join(root, "bin", "gst-launch-1.0.exe")
                    if os.path.isfile(candidate):
                        gst_launch = candidate
                        gst_root = root
                        break
        else:
            gst_root = os.path.dirname(os.path.dirname(gst_launch))
        if not gst_launch:
            return None

        env = os.environ.copy()
        env["GST_REGISTRY_FORK_DISABLE"] = "1"
        env["GST_DEBUG"] = "1"  # suppress WARNINGs, only show ERRORs
        env["GST_PLUGIN_SCANNER"] = os.path.join(gst_root, "libexec", "gstreamer-1.0", "gst-plugin-scanner.exe")
        # Also set PATH so GStreamer DLLs are resolvable
        if gst_root:
            env["PATH"] = os.path.join(gst_root, "bin") + os.pathsep + env.get("PATH", "")

        try:
            import tempfile
            tmp_path = os.path.join(tempfile.gettempdir(),
                                    f"vbplayer_pcm_{os.path.basename(self._filepath)}.pcm")
            # GStreamer pipeline parser treats backslashes as escape chars —
            # use forward slashes which work fine on Windows
            file_uri = self._filepath.replace("\\", "/")
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
            if result.returncode != 0:
                import sys
                err = result.stderr.decode(errors='ignore')[:200] if result.stderr else ""
                sys.stderr.write(f"[gst-launch] FAILED rc={result.returncode} {err}\n")
                return None
            if not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
                return None  # silent — temp file race, not an error
            with open(tmp_path, "rb") as f:
                data = f.read()
            os.unlink(tmp_path)
            return np.frombuffer(data, dtype=np.float32).copy()
        except Exception:
            import sys, traceback
            traceback.print_exc(file=sys.stderr)
            return None

    @staticmethod
    def _find_ffmpeg() -> str | None:
        import shutil
        import os as _os

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        # Search common locations
        candidates = [
            _os.path.join("C:", "/", "msys64", "mingw64", "bin", "ffmpeg.exe"),
            _os.path.join(_os.environ.get("APPDATA", ""), "bilibili", "ffmpeg", "ffmpeg.exe"),
            _os.path.join(_os.environ.get("LOCALAPPDATA", ""), "bilibili", "ffmpeg", "ffmpeg.exe"),
            _os.path.join(_os.environ.get("ProgramFiles", ""), "ffmpeg", "bin", "ffmpeg.exe"),
            _os.path.join(_os.environ.get("USERPROFILE", ""), "ffmpeg", "ffmpeg.exe"),
        ]
        for p in candidates:
            if _os.path.isfile(p):
                return p
        return None

    def _decode_via_ffmpeg(self) -> np.ndarray | None:
        import subprocess
        import shutil
        import os as _os

        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            return None

        try:
            result = subprocess.run(
                [ffmpeg, "-i", self._filepath,
                 "-f", "f32le", "-ac", "1", "-ar", "22050",
                 "-loglevel", "quiet", "pipe:1"],
                capture_output=True, timeout=120,
            )
            if result.returncode != 0 or len(result.stdout) == 0:
                if result.stderr:
                    import sys
                    err = result.stderr.decode(errors='ignore')[:500]
                    sys.stderr.write(f"[ffmpeg] {err}\n")
                    sys.stderr.flush()
                return None
            return np.frombuffer(result.stdout, dtype=np.float32).copy()
        except Exception:
            import sys, traceback
            traceback.print_exc(file=sys.stderr)
            return None

    def _compute_waveform(self, samples: np.ndarray, num_bars: int = 2000) -> np.ndarray:
        window_size = max(1, len(samples) // num_bars)
        num_windows = len(samples) // window_size
        if num_windows < 2:
            return np.abs(samples[:num_bars]) if len(samples) >= num_bars else np.abs(samples)
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

    def _compute_spectrum(self, samples: np.ndarray, bins: int, snapshots_per_sec: int,
                           sample_rate: int = 22050) -> np.ndarray:
        duration = len(samples) / sample_rate
        num_snapshots = max(1, int(duration * snapshots_per_sec))
        chunk_size = max(bins * 4, len(samples) // num_snapshots)
        spectrum = np.zeros((num_snapshots, bins), dtype=np.float64)
        for i in range(num_snapshots):
            start = i * chunk_size
            end = min(start + chunk_size, len(samples))
            if end - start < bins:
                break
            chunk = samples[start:end].copy()
            window = np.hanning(len(chunk))
            chunk = chunk * window
            fft = np.abs(np.fft.rfft(chunk))
            indices = np.linspace(0, len(fft) - 2, bins, dtype=int)
            spec = fft[indices]
            max_val = np.max(spec)
            if max_val > 0:
                spec = spec / max_val
            spec = np.log1p(spec * 3) / np.log1p(3)
            spectrum[i] = spec
        return spectrum

    def _load_lyrics(self) -> list[LyricsLine]:
        """Load lyrics from .lrc file or embedded USLT/SYLT tags."""
        from pathlib import Path

        # Try .lrc file first
        lrc_path = Path(self._filepath).with_suffix(".lrc")
        if lrc_path.exists():
            try:
                return self._parse_lrc(lrc_path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                try:
                    return self._parse_lrc(lrc_path.read_text(encoding="gbk"))
                except Exception as _e:
                    import sys; print(f"[{__name__}] {_e}", file=sys.stderr)

        # Try embedded lyrics via mutagen
        text = self._extract_embedded_lyrics()
        if text:
            # Try parsing as LRC format (embedded LRC has timestamps)
            lrc_lines = self._parse_lrc(text)
            if lrc_lines:
                return lrc_lines
            # Plain text lyrics — split by lines
            raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
            if raw_lines:
                return [LyricsLine(0, line) for line in raw_lines]
        return []

    def _extract_embedded_lyrics(self) -> str | None:
        """Extract lyrics text from embedded tags. Returns None if not found."""
        try:
            import mutagen
            mf = mutagen.File(self._filepath)
            if mf is None or not getattr(mf, 'tags', None):
                return None

            tags = mf.tags
            # Prioritised keys: USLT (ID3), ©lyr (MP4), LYRICS (Vorbis/FLAC)
            for key in tags:
                key_s = str(key)
                if any(k in key_s.upper() for k in ('USLT', '©LYR', 'LYRICS', 'UNSYNCEDLYRICS')):
                    val = tags[key]
                    if isinstance(val, list):
                        val = val[0] if val else None
                    if val is None:
                        continue
                    if hasattr(val, 'text'):
                        t = val.text
                        if isinstance(t, list):
                            t = t[0] if t else None
                        return str(t) if t else None
                    return str(val)
            return None
        except Exception as e:
            import sys; print(f"[analyzer] 元数据读取失败: {e}", file=sys.stderr)
            return None

    def _parse_lrc(self, text: str) -> list[LyricsLine]:
        from audio_player.player.lrc_parser import parse_lrc
        return parse_lrc(text)


class AudioAnalyzer(QObject):
    """Manages background audio analysis with one worker at a time."""
    waveformReady = pyqtSignal(np.ndarray)
    spectrumReady = pyqtSignal(np.ndarray, int)
    lyricsReady = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _DecoderWorker | None = None
        self._request_id = 0

    def analyze(self, filepath: str):
        self._cancel()
        if filepath.startswith(("http://", "https://", "smb://")):
            return
        req_id = self._request_id
        self._worker = _DecoderWorker(filepath, parent=self)
        self._worker.finished.connect(lambda *args: self._on_finished(req_id, *args))
        self._worker.start()

    def _cancel(self):
        """Mark current worker as stale — its results will be ignored."""
        self._request_id += 1

    def _on_finished(self, req_id: int, waveform, spectrum, lyrics):
        if req_id != self._request_id:
            return  # stale result, ignore
        if waveform is not None:
            self.waveformReady.emit(waveform)
        if spectrum is not None:
            self.spectrumReady.emit(spectrum, 22050)
        self.lyricsReady.emit(lyrics)
