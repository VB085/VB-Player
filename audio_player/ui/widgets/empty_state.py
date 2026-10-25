"""Shared empty-state widget — icon, one line, one hint, optional action.

Replaces the bare 13px gray labels that used to sit forgotten in a grid
corner. Vertically and horizontally centered in whatever container it
lands in; keep a reference and call setParent/None to show/hide.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from audio_player.app import current_accent
from audio_player.i18n import _
from audio_player.ui.icons import _icon


class EmptyStateWidget(QWidget):
    """Centered empty-state: icon in a soft circle, title, hint, button."""

    actionClicked = pyqtSignal()

    def __init__(self, icon_name: str, title: str, hint: str = "",
                 action_text: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("emptyStateWidget")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Icon in a soft circle
        circle = QLabel()
        circle.setFixedSize(64, 64)
        circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        accent = current_accent()
        circle.setStyleSheet(
            f"background:rgba({accent.red()},{accent.green()},{accent.blue()},0.10);"
            f"border-radius:32px;")
        icon_lbl_size = 26
        circle.setPixmap(_icon(icon_name, color="#777").pixmap(icon_lbl_size, icon_lbl_size))
        lay.addWidget(circle, 0, Qt.AlignmentFlag.AlignCenter)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("emptyTitle")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title_lbl)

        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setObjectName("emptyHint")
            hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(hint_lbl)

        if action_text:
            btn = QPushButton(action_text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            accent = current_accent()
            btn.setStyleSheet(
                f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
                f"border-radius:8px;padding:7px 18px;font-size:12px;}}"
                f"QPushButton:hover{{background:{accent.lighter(115).name()};}}")
            btn.clicked.connect(self.actionClicked.emit)
            wrap = QWidget()
            hw = QHBoxLayout(wrap)
            hw.setContentsMargins(0, 4, 0, 0)
            hw.addStretch(1)
            hw.addWidget(btn)
            hw.addStretch(1)
            lay.addWidget(wrap)
            self._action_btn = btn
