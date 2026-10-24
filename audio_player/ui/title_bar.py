"""Title bar widget with minimize/maximize/close buttons and window drag.

Caption buttons mimic native Windows 11: 46×32 hit targets flush to the
top-right corner, 1px line glyphs painted with QPainter, 10% hover veil,
red hover on close, and a maximize↔restore glyph switch.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QRectF, QPointF
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QPen

from audio_player.i18n import _


class _CaptionButton(QPushButton):
    """Win11-style flat caption button with painted line glyph."""

    _HOVER_DARK = QColor(255, 255, 255, 26)    # 10% white veil
    _HOVER_LIGHT = QColor(0, 0, 0, 20)
    _PRESS_DARK = QColor(255, 255, 255, 52)
    _PRESS_LIGHT = QColor(0, 0, 0, 40)
    _CLOSE_HOVER = QColor(0xc4, 0x2b, 0x1c)    # Win11 system close red
    _CLOSE_PRESS = QColor(0xb3, 0x27, 0x1e)

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind          # "min" | "max" | "close"
        self._hovered = False
        self._pressed = False
        self.setFixedSize(46, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:transparent;border:none;")
        tooltips = {"min": _("window.minimize"), "max": _("window.maximize"),
                    "close": _("window.close")}
        self.setToolTip(tooltips.get(kind, ""))
        self.setAccessibleName(self.toolTip())

    def _is_light(self) -> bool:
        return self.palette().color(self.palette().ColorRole.Window).lightness() > 128

    def enterEvent(self, ev):
        self._hovered = True; self.update()

    def leaveEvent(self, ev):
        self._hovered = False; self._pressed = False; self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._pressed = True; self.update()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._pressed = False; self.update()
        super().mouseReleaseEvent(ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        light = self._is_light()

        # ── Hover / press fill ─────────────────────────────────────
        if self._kind == "close" and self._hovered:
            fill = self._CLOSE_PRESS if self._pressed else self._CLOSE_HOVER
            p.fillRect(0, 0, w, h, fill)
        elif self._hovered:
            if light:
                fill = self._PRESS_LIGHT if self._pressed else self._HOVER_LIGHT
            else:
                fill = self._PRESS_DARK if self._pressed else self._HOVER_DARK
            p.fillRect(0, 0, w, h, fill)

        # ── Glyph ──────────────────────────────────────────────────
        glyph = QColor("#fff") if (self._kind == "close" and self._hovered) else \
            (QColor("#333") if light else QColor("#ccc"))
        pen = QPen(glyph, 1.0)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        if self._kind == "min":
            p.drawLine(QRectF(cx - 5, cy - 0.5, 10, 0).topLeft(),
                       QRectF(cx - 5, cy - 0.5, 10, 0).topRight())
        elif self._kind == "max":
            if self.window() is not None and self.window().isMaximized():
                # Restore: two overlapping rect outlines
                back = QRectF(cx - 5 + 3, cy - 5 - 3, 9, 9)
                front = QRectF(cx - 5 - 2, cy - 5 + 2, 9, 9)
                p.drawRect(back.adjusted(0.5, 0.5, -0.5, -0.5))
                p.drawRect(front.adjusted(0.5, 0.5, -0.5, -0.5))
            else:
                r = QRectF(cx - 5, cy - 5, 10, 10).adjusted(0.5, 0.5, -0.5, -0.5)
                p.drawRect(r)
        elif self._kind == "close":
            p.drawLine(QPointF(cx - 4.5, cy - 4.5), QPointF(cx + 4.5, cy + 4.5))
            p.drawLine(QPointF(cx + 4.5, cy - 4.5), QPointF(cx - 4.5, cy + 4.5))
        p.end()


class TitleBar(QWidget):
    """Custom frameless title bar. Emits signals instead of calling
    window methods directly."""

    minimizeClicked = pyqtSignal()
    maximizeClicked = pyqtSignal()
    closeClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("VB Player")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        layout.addStretch()

        min_btn = _CaptionButton("min")
        min_btn.clicked.connect(self.minimizeClicked.emit)
        layout.addWidget(min_btn)

        max_btn = _CaptionButton("max")
        max_btn.clicked.connect(self.maximizeClicked.emit)
        layout.addWidget(max_btn)
        self._max_btn = max_btn

        close_btn = _CaptionButton("close")
        close_btn.clicked.connect(self.closeClicked.emit)
        layout.addWidget(close_btn)

        # Repaint the max button when the window state changes
        # (WindowStateChange is only delivered to the window itself)
        win = self.window()
        if win is not None:
            win.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.WindowStateChange:
            maximized = self.window() is not None and self.window().isMaximized()
            self._max_btn.setToolTip(_("window.restore") if maximized else _("window.maximize"))
            self._max_btn.update()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            wh = self.window().windowHandle()
            if wh:
                wh.startSystemMove()

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()
