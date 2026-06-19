from PyQt6.QtWidgets import QWidget, QLabel, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QRectF, QSize
from PyQt6.QtGui import (QPainter, QColor, QPixmap, QImage, QPainterPath,
                         QLinearGradient, QFont)
from audio_player.ui.utils import cover_corner_radius


class CoverArtWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self._cover: QPixmap | None = None
        self._placeholder_text = ""

    def set_cover(self, data: bytes | None, fallback_text: str = ""):
        self._placeholder_text = fallback_text[:1].upper() if fallback_text else "♪"
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                self._cover = pix
                self.update()
                return
        self._cover = None
        self.update()

    def clear(self):
        self._cover = None
        self._placeholder_text = "♪"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w = self.width()
        h = min(self.height(), w)
        margin = 10
        size = min(w - margin * 2, h - margin * 2)
        x = (w - size) / 2
        y = margin
        r = cover_corner_radius()

        cover_rect = QRectF(x, y, size, size)

        # Shadow
        shadow_rect = cover_rect.translated(2, 4)
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(shadow_rect, r, r)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawPath(shadow_path)

        if self._cover and not self._cover.isNull():
            # Clip to rounded rect
            clip_path = QPainterPath()
            clip_path.addRoundedRect(cover_rect, r, r)
            painter.setClipPath(clip_path)

            scaled = self._cover.scaled(
                int(size), int(size),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            src_x = (scaled.width() - size) / 2
            src_rect = QRectF(src_x, 0, size, size)
            painter.drawPixmap(cover_rect, scaled, src_rect)

            painter.setClipping(False)

            # Subtle overlay gradient for depth
            overlay = QLinearGradient(cover_rect.topLeft(), cover_rect.bottomRight())
            overlay.setColorAt(0.0, QColor(255, 255, 255, 0))
            overlay.setColorAt(1.0, QColor(0, 0, 0, 30))
            painter.setBrush(overlay)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(cover_rect, r, r)

        else:
            # Placeholder
            grad = QLinearGradient(cover_rect.topLeft(), cover_rect.bottomRight())
            grad.setColorAt(0.0, QColor("#1e1e40"))
            grad.setColorAt(1.0, QColor("#2d1b69"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawRoundedRect(cover_rect, r, r)

            # Music note icon
            font = QFont()
            font.setPointSize(int(size / 4))
            painter.setFont(font)
            painter.setPen(QColor("#a78bfa"))
            painter.drawText(cover_rect, Qt.AlignmentFlag.AlignCenter,
                             self._placeholder_text)

        painter.end()
