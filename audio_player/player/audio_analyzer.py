from PyQt6.QtCore import QObject, QThread, pyqtSignal, QMutex, QWaitCondition
import numpy as np
import subprocess
import shutil
from dataclasses import dataclass


@dataclass
class LyricsLine:
    time_ms: int
    text: str
    translation: str = ""  # paired bilingual translation line


class _DecoderWorker(QThread):
    finished = pyqtSignal(object, object, object)  # waveform, spectrum, lyrics

    def __init__(self, filepath: str, bins: int = 64, snapshots_per_sec: int = 30):
        super().__init__()
        self._filepath = filepath
        self._bins = bins
        self._snapshots_per_sec = snapshots_per_sec

    def run(self):
        waveform = None
        spectrum = None
        lyrics = []
        samples = self._decode_to_pcm()
        if samples is not None and len(samples) > 0:
            waveform = self._compute_waveform(samples)
            spectrum = self._compute_spectrum(samples, self._bins, self._snapshots_per_sec)
        lyrics = self._load_lyrics()
        self.finished.emit(waveform, spectrum, lyrics)

    def _decode_to_pcm(self) -> np.ndarray | None:
        if not shutil.which("gst-launch-1.0"):
            return None
        try:
            result = subprocess.run(
                ["gst-launch-1.0", "-q",
                 "filesrc", f"location={self._filepath}",
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
                except Exception:
                    pass

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
        except Exception:
            return None

    def _parse_lrc(self, text: str) -> list[LyricsLine]:
        import re
        lines = []
        for line in text.splitlines():
            # Match: [mm:ss.xx] or [mm:ss.xxx]
            matches = list(re.finditer(r'\[(\d+):(\d+(?:\.\d+)?)\]', line))
            if not matches:
                continue
            lyric_text = line[matches[-1].end():].strip()
            if not lyric_text:
                continue
            for m in matches:
                minutes = int(m.group(1))
                seconds = float(m.group(2))
                time_ms = int((minutes * 60 + seconds) * 1000)
                lines.append(LyricsLine(time_ms, lyric_text))
        # Sort by time
        lines.sort(key=lambda x: x.time_ms)
        # Merge same-timestamp lines as original + translation pairs
        merged = []
        i = 0
        while i < len(lines):
            if i + 1 < len(lines) and lines[i].time_ms == lines[i + 1].time_ms:
                merged.append(LyricsLine(lines[i].time_ms, lines[i].text, lines[i + 1].text))
                i += 2
            else:
                merged.append(lines[i])
                i += 1
        return merged


class AudioAnalyzer(QObject):
    """Manages background audio analysis with one worker at a time."""
    waveformReady = pyqtSignal(np.ndarray)
    spectrumReady = pyqtSignal(np.ndarray, int)
    lyricsReady = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _DecoderWorker | None = None

    def analyze(self, filepath: str):
        self._cancel()
        self._worker = _DecoderWorker(filepath)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.finished.disconnect()
            self._worker.quit()
            self._worker.wait(1000)

    def _on_finished(self, waveform, spectrum, lyrics):
        if waveform is not None:
            self.waveformReady.emit(waveform)
        if spectrum is not None:
            self.spectrumReady.emit(spectrum, 22050)
        self.lyricsReady.emit(lyrics)
