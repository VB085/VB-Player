"""QML-based HiFi Now Playing page."""
import os
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtQuickWidgets import QQuickWidget


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
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

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
        if not cover_data: return
        pix = QPixmap(); pix.loadFromData(cover_data)
        if pix.isNull(): return
        import tempfile, time
        from audio_player.ui.widgets.hifi_now_playing import _blur_pixmap
        self._cover_path = os.path.join(tempfile.gettempdir(), "vbplayer_hifi_cover.jpg")
        pix.save(self._cover_path, "JPG", 85)
        small = pix.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        blurred_small = _blur_pixmap(small, radius=8)
        blurred = blurred_small.scaled(pix.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._bg_path = os.path.join(tempfile.gettempdir(), "vbplayer_hifi_bg.jpg")
        blurred.save(self._bg_path, "JPG", 85)
        root = self.rootObject()
        if root:
            ts = str(int(time.time()*1000))
            root.setProperty("coverPath", QUrl.fromLocalFile(self._cover_path).toString()+"?t="+ts)
            root.setProperty("bgPath", QUrl.fromLocalFile(self._bg_path).toString()+"?t="+ts)

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
        if root:
            dict_lines = []
            for line in (lines or []):
                if hasattr(line, '__dataclass_fields__'):
                    dict_lines.append({'timeMs': line.time_ms, 'text': line.text, 'translation': line.translation or ''})
                elif isinstance(line, dict):
                    dict_lines.append(line)
            root.setProperty("lyricsModel", dict_lines)

    def set_lyrics_position(self, ms: int):
        root = self.rootObject()
        if root is None: return
        lyrics_val = root.property("lyricsModel")
        if lyrics_val is None: return
        try: lyrics = lyrics_val.toVariant()
        except AttributeError: return
        if not lyrics: return
        new_idx = -1
        for i, line in enumerate(lyrics):
            t = line.get("timeMs", line.get("time_ms", 0)) if isinstance(line, dict) else 0
            if t <= ms: new_idx = i
            else: break
        root.setProperty("lyricsActiveIdx", new_idx)

    def refresh_accent(self):
        from audio_player.app import current_accent
        accent = current_accent()
        root = self.rootObject()
        if root: root.setProperty("accentColor", accent)
