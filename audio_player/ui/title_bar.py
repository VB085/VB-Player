"""Title bar widget with minimize/maximize/close buttons and window drag."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QPen, QFont
from PyQt6.QtCore import QRectF

from audio_player.ui.settings_dialog import _CloseButton


class _TitleBarButton(QPushButton):
    """Minimal circular button with painted symbol — matches _CloseButton style."""

    def __init__(self, text: str, size=28, parent=None):
        super().__init__(parent)
        self._text = text
        self._hovered = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:transparent;border:none;")

    def enterEvent(self, ev):
        self._hovered = True; self.update()

    def leaveEvent(self, ev):
        self._hovered = False; self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 2
        # Hover background
        if self._hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 20))
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        # Symbol
        p.setPen(QColor("#ccc"))
        f = QFont(); f.setPointSize(10); p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
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
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(2)

        title = QLabel("VB Player")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        layout.addStretch()

        # Minimize button
        min_btn = _TitleBarButton("─", 28)
        min_btn.clicked.connect(self.minimizeClicked.emit)
        layout.addWidget(min_btn)

        # Maximize button
        max_btn = _TitleBarButton("□", 28)
        max_btn.clicked.connect(self.maximizeClicked.emit)
        layout.addWidget(max_btn)

        # Close button (same size, red hover via _CloseButton)
        close_btn = _CloseButton(28)
        close_btn.clicked.connect(self.closeClicked.emit)
        layout.addWidget(close_btn)

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
