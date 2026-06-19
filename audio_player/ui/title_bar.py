"""Title bar widget with minimize/maximize/close buttons and window drag."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent

from audio_player.ui.settings_dialog import _CloseButton


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
        layout.setSpacing(0)

        title = QLabel("VB Player")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        layout.addStretch()

        # Minimize button
        min_btn = QPushButton("─")
        min_btn.setObjectName("minBtn")
        min_btn.setFixedSize(36, 24)
        min_btn.setAccessibleName("Minimize")
        min_btn.clicked.connect(self.minimizeClicked.emit)
        layout.addWidget(min_btn)

        # Maximize button
        max_btn = QPushButton("□")
        max_btn.setObjectName("maxBtn")
        max_btn.setFixedSize(36, 24)
        max_btn.setAccessibleName("Maximize")
        max_btn.clicked.connect(self.maximizeClicked.emit)
        layout.addWidget(max_btn)

        # Close button
        close_btn = _CloseButton()
        close_btn.setObjectName("closeBtn")
        close_btn.setAccessibleName("Close")
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
