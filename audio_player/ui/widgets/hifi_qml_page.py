"""QML-based HiFi Now Playing page."""
import bisect
import os
import queue
import tempfile
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QThread
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtQuickWidgets import QQuickWidget
from PyQt6.QtWidgets import QApplication


class _CoverWorker(QThread):
    """Prepares cover art off the UI thread: decode → blur → JPEG export.

    Mirrors the _MetaLoader pattern (persistent thread + queue). Uses only
    QImage/numpy — no QPixmap, which is not usable outside the GUI thread.
    Results carry a generation counter so stale entries (user switched tracks
    mid-blur) are dropped by the consumer.
    """
    coverReady = pyqtSignal(int, str, str)  # generation, cover_path, bg_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._running = True

    def enqueue(self, gen: int, data: bytes):
        self._queue.put((gen, data))
        if not self.isRunning():
            self.start()

    def stop(self):
        self._running = False
        self._queue.put((-1, None))
        self.wait(2000)

    def run(self):
        from audio_player.ui.widgets.hifi_now_playing import _blur_qimage
        while self._running:
            try:
                gen, data = self._queue.get(timeout=1)
            except Exception:
                continue
            if not self._running or gen < 0:
                break
            try:
                img = QImage.fromData(data)
                if img.isNull():
                    continue
                small = img.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                blurred = _blur_qimage(small, radius=8)
                bg = blurred.scaled(img.width(), img.height(),
                                    Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                cover_path = os.path.join(tempfile.gettempdir(),
                                          f"vbplayer_hifi_cover_{gen}.jpg")
                bg_path = os.path.join(tempfile.gettempdir(),
                                       f"vbplayer_hifi_bg_{gen}.jpg")
                img.save(cover_path, "JPG", 85)
                bg.save(bg_path, "JPG", 85)
                # Best-effort cleanup of the previous generation's files
                for old in (f"vbplayer_hifi_cover_{gen - 1}.jpg",
                            f"vbplayer_hifi_bg_{gen - 1}.jpg"):
                    try:
                        os.unlink(os.path.join(tempfile.gettempdir(), old))
                    except OSError:
                        pass
                self.coverReady.emit(gen, cover_path, bg_path)
            except Exception:
                continue


class HiFiQmlPage(QQuickWidget):
    collapseRequested = pyqtSignal()
    fullscreenRequested = pyqtSignal()
    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    seekRequested = pyqtSignal(int)
    lyricsToggled = pyqtSignal(bool)
    outputDetailRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hifiQmlPage")
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setClearColor(Qt.GlobalColor.transparent)

        # Export icons
        import tempfile
        self._icon_dir = os.path.join(tempfile.gettempdir(), "vbplayer_qml_icons")
        os.makedirs(self._icon_dir, exist_ok=True)
        self._export_icons()

        # Load QML
        qml_path = Path(__file__).resolve().parent.parent / "qml" / "HiFiNowPlaying.qml"
        self.setSource(QUrl.fromLocalFile(str(qml_path)))

        root = self.rootObject()
        if root is not None:
            root.collapseRequested.connect(self.collapseRequested.emit)
            root.fullscreenRequested.connect(self.fullscreenRequested.emit)
            root.playPauseClicked.connect(self.playPauseClicked.emit)
            root.nextClicked.connect(self.nextClicked.emit)
            root.prevClicked.connect(self.prevClicked.emit)
            root.seekRequested.connect(self.seekRequested.emit)
            root.lyricsToggled.connect(self.lyricsToggled.emit)
            for name in ('prev', 'play', 'pause', 'next'):
                root.setProperty(f"icon{name.capitalize()}",
                    QUrl.fromLocalFile(os.path.join(self._icon_dir, f"{name}.png")).toString())

        self._position_ms = 0
        self._duration_ms = 0
        self._is_playing = False
        self._cover_worker: _CoverWorker | None = None
        self._cover_gen = 0
        self._lyrics_times: list[int] = []
        self._last_lyrics_idx = -2
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_cover_worker)

    def _stop_cover_worker(self):
        if self._cover_worker is not None:
            self._cover_worker.stop()
            self._cover_worker = None

    def _export_icons(self):
        from audio_player.ui.icons import TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon
        icon_map = {'prev': (TRANSPORT_PREV, '#cccccc'), 'play': (TRANSPORT_PLAY, '#ffffff'),
                    'pause': (TRANSPORT_PAUSE, '#ffffff'), 'next': (TRANSPORT_NEXT, '#cccccc')}
        for name, (icon_name, color) in icon_map.items():
            path = os.path.join(self._icon_dir, f"{name}.png")
            if not os.path.exists(path):
                icon = _icon(icon_name, color=color)
                pix = icon.pixmap(64, 64)
                pix.save(path, "PNG")

    def set_track_info(self, title: str, artist: str, album: str):
        root = self.rootObject()
        if root: root.setProperty("trackTitle", title or "")
        if root: root.setProperty("trackArtist", artist or "")
        if root: root.setProperty("trackAlbum", album or "")

    def set_cover(self, cover_data: bytes | None):
        """Queue cover preparation on the worker thread — the UI thread only
        hands over bytes and applies the finished URLs (see _on_cover_ready)."""
        if not cover_data:
            return
        if self._cover_worker is None:
            self._cover_worker = _CoverWorker(self)
            self._cover_worker.coverReady.connect(self._on_cover_ready)
        self._cover_gen += 1
        self._cover_worker.enqueue(self._cover_gen, cover_data)

    def _on_cover_ready(self, gen: int, cover_path: str, bg_path: str):
        if gen != self._cover_gen:
            return  # stale — a newer track already took over
        root = self.rootObject()
        if root:
            # Unique per-generation filenames, so no cache-buster query needed
            root.setProperty("coverPath", QUrl.fromLocalFile(cover_path).toString())
            root.setProperty("bgPath", QUrl.fromLocalFile(bg_path).toString())

    def set_position(self, ms: int):
        self._position_ms = ms
        root = self.rootObject()
        if root: root.setProperty("positionMs", ms)

    def set_duration(self, ms: int):
        self._duration_ms = ms
        root = self.rootObject()
        if root: root.setProperty("durationMs", ms)

    def set_playing(self, playing: bool):
        self._is_playing = playing
        root = self.rootObject()
        if root: root.setProperty("isPlaying", playing)

    def set_quality(self, text: str):
        root = self.rootObject()
        if root:
            root.setProperty("qualityText", text or "")
            if text and " · " in text:
                root.setProperty("qualitySimple", " · ".join(text.split(" · ")[:2]))
            else:
                root.setProperty("qualitySimple", text or "")

    def set_lyrics_visible(self, visible: bool):
        root = self.rootObject()
        if root: root.setProperty("lyricsLayoutProgress", 1.0 if visible else 0.0)

    def set_lyrics(self, lines: list):
        root = self.rootObject()
        dict_lines = []
        for line in (lines or []):
            if hasattr(line, '__dataclass_fields__'):
                dict_lines.append({'timeMs': line.time_ms, 'text': line.text, 'translation': line.translation or ''})
            elif isinstance(line, dict):
                dict_lines.append(line)
        self._lyrics_times = [d.get('timeMs', d.get('time_ms', 0)) for d in dict_lines]
        self._last_lyrics_idx = -2
        if root:
            root.setProperty("lyricsModel", dict_lines)

    def set_lyrics_position(self, ms: int):
        """Binary-search the active line over cached timestamps — avoids
        re-converting the whole lyrics model on every position update."""
        if not self._lyrics_times:
            return
        new_idx = bisect.bisect_right(self._lyrics_times, ms) - 1
        if new_idx == self._last_lyrics_idx:
            return
        self._last_lyrics_idx = new_idx
        root = self.rootObject()
        if root:
            root.setProperty("lyricsActiveIdx", new_idx)

    def refresh_accent(self):
        from audio_player.app import current_accent
        accent = current_accent()
        root = self.rootObject()
        if root: root.setProperty("accentColor", accent)
