"""Now Playing overlay — HiFi-style immersive page with slide-up from bottom bar."""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QSlider, QGraphicsOpacityEffect)
from PyQt6.QtCore import (Qt, pyqtSignal, QPropertyAnimation, QEasingCurve,
                          QRect, QPoint, QTimer)
from PyQt6.QtGui import (QPainter, QColor, QPixmap, QFont, QLinearGradient,
                         QPainterPath, QBrush, QPen)

from audio_player.app import current_accent, current_theme_mode
from audio_player.ui.icons import (
    TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT,
    MODE_SHUFFLE, MODE_REPEAT_ALL, VOLUME_LOW, _icon,
)
from audio_player.ui.utils import format_duration


def _blur_pixmap(pix: QPixmap, radius: int = 40) -> QPixmap:
    """Multi-pass box blur for background."""
    if pix.isNull():
        return pix
    small = pix.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    img = small.toImage()
    w, h = img.width(), img.height()
    for _ in range(3):
        for y in range(h):
            row = [img.pixelColor(x, y) for x in range(w)]
            for x in range(w):
                r = g = b = cnt = 0
                for dx in range(-radius // 4, radius // 4 + 1):
                    nx = min(max(x + dx, 0), w - 1)
                    c = row[nx]
                    r += c.red(); g += c.green(); b += c.blue(); cnt += 1
                img.setPixelColor(x, y, QColor(r // cnt, g // cnt, b // cnt))
        for x in range(w):
            col = [img.pixelColor(x, y) for y in range(h)]
            for y in range(h):
                r = g = b = cnt = 0
                for dy in range(-radius // 4, radius // 4 + 1):
                    ny = min(max(y + dy, 0), h - 1)
                    c = col[ny]
                    r += c.red(); g += c.green(); b += c.blue(); cnt += 1
                img.setPixelColor(x, y, QColor(r // cnt, g // cnt, b // cnt))
    result = QPixmap.fromImage(img)
    return result.scaled(pix.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


class NowPlayingPage(QWidget):
    """Immersive Now Playing page — slides up from bottom bar on click."""

    collapseRequested = pyqtSignal()
    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    seekRequested = pyqtSignal(int)
    volumeChanged = pyqtSignal(float)
    immersiveRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nowPlayingPage")
        self._cover_pixmap: QPixmap | None = None
        self._blurred_bg: QPixmap | None = None
        self._title = ""
        self._artist = ""
        self._album = ""
        self._position_ms = 0
        self._duration_ms = 0
        self._is_playing = False
        self._dragging = False
        self._accent = current_accent()

        # Slide-up animation
        self._slide_anim = QPropertyAnimation(self, b"geometry")
        self._slide_anim.setDuration(350)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setMouseTracking(True)

        # ── Buttons (absolutely positioned) ──
        btn_css = (
            "QPushButton{background:rgba(255,255,255,0.12);color:#ccc;border:none;"
            "border-radius:18px;font-size:15px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.22);color:#fff;}"
        )
        self._close_btn = QPushButton("✕", self)
        self._close_btn.setFixedSize(36, 36)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.collapseRequested.emit)
        self._close_btn.setStyleSheet(btn_css)

        self._immersive_btn = QPushButton("⛶", self)
        self._immersive_btn.setFixedSize(36, 36)
        self._immersive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._immersive_btn.clicked.connect(self.immersiveRequested.emit)
        self._immersive_btn.setStyleSheet(btn_css)

    # ── Public API ──

    def set_cover(self, cover_data: bytes | None):
        if cover_data:
            pix = QPixmap()
            pix.loadFromData(cover_data)
            if not pix.isNull():
                self._cover_pixmap = pix
                self._blurred_bg = None
                self.update()
                return
        self._cover_pixmap = None
        self._blurred_bg = None
        self.update()

    def set_track(self, title: str, artist: str, album: str):
        self._title = title or ""
        self._artist = artist or ""
        self._album = album or ""
        self.update()

    def set_position(self, ms: int):
        self._position_ms = ms
        self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self.update()

    def set_playing(self, playing: bool):
        self._is_playing = playing
        self.update()

    def set_volume(self, vol: float):
        pass  # handled by slider internally

    def set_lyrics(self, _lines):
        pass  # HiFi page handles lyrics; NP page is pure art display

    def set_quality(self, text: str): pass
    def set_file_info(self, text: str): pass

    # ── Animation ──

    def animate_in(self, from_rect: QRect, to_rect: QRect):
        """Slide up from bottom bar position to full overlay."""
        self._slide_anim.stop()
        self._slide_anim.setStartValue(from_rect)
        self._slide_anim.setEndValue(to_rect)
        self._slide_anim.start()

    # ── Paint ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background: blurred cover or fallback gradient
        if self._cover_pixmap:
            if self._blurred_bg is None:
                self._blurred_bg = _blur_pixmap(
                    self._cover_pixmap.scaled(w, h,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation))
            painter.drawPixmap(0, 0, self._blurred_bg)
            # Dark overlay for readability
            painter.fillRect(self.rect(), QColor(0, 0, 0, 140))
        else:
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0.0, QColor("#1a1a2e"))
            grad.setColorAt(1.0, QColor("#0f0f1a"))
            painter.fillRect(self.rect(), QBrush(grad))

        # ── Layout ──
        margin = 60
        usable_h = h - margin * 2
        art_size = min(300, int(usable_h * 0.48))

        # Album art — centered horizontally, slightly above center vertically
        art_x = (w - art_size) // 2
        art_y = margin + 20

        if self._cover_pixmap:
            scaled = self._cover_pixmap.scaled(art_size, art_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            ax = art_x + (art_size - scaled.width()) // 2
            ay = art_y + (art_size - scaled.height()) // 2
            # Shadow
            shadow_rect = QPainterPath()
            shadow_rect.addRoundedRect(ax - 4, ay - 4, scaled.width() + 8,
                                       scaled.height() + 8, 12, 12)
            painter.fillPath(shadow_rect, QColor(0, 0, 0, 80))
            # Artwork with rounded corners
            clip = QPainterPath()
            clip.addRoundedRect(ax, ay, scaled.width(), scaled.height(), 8, 8)
            painter.setClipPath(clip)
            painter.drawPixmap(ax, ay, scaled)
            painter.setClipping(False)

        # Title + Artist
        text_y = art_y + art_size + 24
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffffff"))
        title_text = painter.fontMetrics().elidedText(
            self._title or "VB Player", Qt.TextElideMode.ElideRight, w - 120)
        painter.drawText(0, text_y, w, 32, Qt.AlignmentFlag.AlignCenter,
                         title_text)

        artist_font = QFont()
        artist_font.setPointSize(14)
        painter.setFont(artist_font)
        painter.setPen(QColor(255, 255, 255, 180))
        artist_text = self._artist
        if self._album and self._album != self._artist:
            artist_text = f"{self._artist} — {self._album}" if self._artist else self._album
        artist_text = painter.fontMetrics().elidedText(
            artist_text, Qt.TextElideMode.ElideRight, w - 120)
        painter.drawText(0, text_y + 34, w, 24, Qt.AlignmentFlag.AlignCenter,
                         artist_text)

        # ── Progress bar ──
        progress_y = h - 140
        pb_margin = 80
        pb_w = w - pb_margin * 2
        pb_h = 4
        pb_x = pb_margin

        # Elapsed / remaining
        time_font = QFont()
        time_font.setPointSize(10)
        painter.setFont(time_font)
        painter.setPen(QColor(255, 255, 255, 120))
        elapsed = format_duration(self._position_ms / 1000)
        remaining = format_duration(self._duration_ms / 1000)
        painter.drawText(pb_x, progress_y - 8, 50, 16,
                         Qt.AlignmentFlag.AlignLeft, elapsed)
        painter.drawText(pb_x + pb_w - 50, progress_y - 8, 50, 16,
                         Qt.AlignmentFlag.AlignRight, remaining)

        # Groove
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 30))
        painter.drawRoundedRect(pb_x, progress_y, pb_w, pb_h, 2, 2)

        # Filled
        if self._duration_ms > 0:
            ratio = self._position_ms / self._duration_ms
            fill_w = int(pb_w * ratio)
            painter.setBrush(self._accent)
            painter.drawRoundedRect(pb_x, progress_y, fill_w, pb_h, 2, 2)

            # Handle
            hx = pb_x + fill_w
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(hx - 6, progress_y - 4, 12, 12)

        # ── Transport controls ──
        ctrl_y = progress_y + 36
        ctrl_w = 44
        total_ctrl_w = ctrl_w * 5 + 16 * 4  # 5 buttons with spacing

        def draw_ctrl_btn(cx, icon_name, is_play=False):
            r = QPainterPath()
            size = 52 if is_play else ctrl_w
            r.addEllipse(cx - size // 2, ctrl_y - size // 2, size, size)
            if is_play:
                painter.fillPath(r, self._accent)
            else:
                painter.fillPath(r, QColor(255, 255, 255, 25))
            icon = _icon(icon_name, color="#fff" if is_play else "#ccc")
            pix = icon.pixmap(size - 16, size - 16)
            painter.drawPixmap(cx - pix.width() // 2, ctrl_y - pix.height() // 2, pix)

        start_x = (w - total_ctrl_w) // 2 + ctrl_w // 2
        draw_ctrl_btn(start_x, MODE_SHUFFLE)
        draw_ctrl_btn(start_x + ctrl_w + 16, TRANSPORT_PREV)
        draw_ctrl_btn(start_x + (ctrl_w + 16) * 2, TRANSPORT_PAUSE if self._is_playing else TRANSPORT_PLAY, True)
        draw_ctrl_btn(start_x + (ctrl_w + 16) * 3, TRANSPORT_NEXT)
        draw_ctrl_btn(start_x + (ctrl_w + 16) * 4, MODE_REPEAT_ALL)

        # ── Volume ──
        vol_y = ctrl_y + 50
        vol_w = 140
        vol_x = (w - vol_w) // 2
        vol_icon = _icon(VOLUME_LOW, color="#888")
        painter.drawPixmap(vol_x - 24, vol_y - 4, vol_icon.pixmap(16, 16))
        painter.setBrush(QColor(255, 255, 255, 25))
        painter.drawRoundedRect(vol_x, vol_y, vol_w, 3, 1.5, 1.5)
        painter.setBrush(QColor(255, 255, 255, 80))
        painter.drawRoundedRect(vol_x, vol_y, int(vol_w * 0.7), 3, 1.5, 1.5)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(vol_x + int(vol_w * 0.7) - 5, vol_y - 3, 10, 10)

        painter.end()

    # ── Mouse events ──

    def mousePressEvent(self, e):
        w, h = self.width(), self.height()
        progress_y = h - 140
        pb_x, pb_w = 80, w - 160
        if progress_y - 8 <= e.pos().y() <= progress_y + 16 and pb_x <= e.pos().x() <= pb_x + pb_w:
            self._dragging = True
            self._seek_to_x(e.pos().x())
        # Re-emit for button clicks: close / immersive
        # Forward clicks to absolute-positioned buttons
        if e.pos().y() <= 44:
            if e.pos().x() >= w - 88 and e.pos().x() <= w - 52:
                self.immersiveRequested.emit()
            elif e.pos().x() >= w - 44:
                self.collapseRequested.emit()
        # Transport area
        ctrl_y = progress_y + 36
        ctrl_w = 44
        total_w = ctrl_w * 5 + 16 * 4
        start_x = (w - total_w) // 2 + ctrl_w // 2
        if ctrl_y - 26 <= e.pos().y() <= ctrl_y + 26:
            x = e.pos().x()
            if abs(x - start_x) <= 22:        self._on_shuffle()
            elif abs(x - (start_x + ctrl_w + 16)) <= 22: self.prevClicked.emit()
            elif abs(x - (start_x + (ctrl_w + 16) * 2)) <= 26: self.playPauseClicked.emit()
            elif abs(x - (start_x + (ctrl_w + 16) * 3)) <= 22: self.nextClicked.emit()
            elif abs(x - (start_x + (ctrl_w + 16) * 4)) <= 22: self._on_repeat()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._seek_to_x(e.pos().x())

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            self._seek_to_x(e.pos().x())

    def _seek_to_x(self, x):
        w = self.width()
        pb_x, pb_w = 80, w - 160
        ratio = max(0.0, min(1.0, (x - pb_x) / pb_w))
        self.seekRequested.emit(int(ratio * self._duration_ms))

    def _on_shuffle(self):
        pass  # connected externally

    def _on_repeat(self):
        pass  # connected externally

    # ── Resize ──

    def resizeEvent(self, event):
        w = self.width()
        self._close_btn.move(w - 44, 8)
        self._immersive_btn.move(w - 88, 8)
        self._blurred_bg = None  # invalidate on resize
        super().resizeEvent(event)

    # ── Theme ──

    def refresh_theme(self):
        self.update()

    def refresh_accent(self):
        self._accent = current_accent()
        self.update()
