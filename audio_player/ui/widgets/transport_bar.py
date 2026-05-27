from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from audio_player.app import current_accent
from audio_player.i18n import _


class TransportBar(QWidget):
    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transportBar")
        self._is_playing = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(24)
        layout.addStretch()

        self._prev_btn = QPushButton("⏮")
        self._prev_btn.setToolTip(_("transport.prev"))
        self._prev_btn.clicked.connect(self.prevClicked)
        layout.addWidget(self._prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._play_btn = QPushButton("▶")
        self._play_btn.setObjectName("playBtn")
        self._play_btn.setToolTip(_("transport.play"))
        self._play_btn.clicked.connect(self.playPauseClicked)
        layout.addWidget(self._play_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._next_btn = QPushButton("⏭")
        self._next_btn.setToolTip(_("transport.next"))
        self._next_btn.clicked.connect(self.nextClicked)
        layout.addWidget(self._next_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch()
        self._apply_sizing()

    def _apply_sizing(self):
        ref_h = max(self.height(), 360)
        scale = max(0.8, min(1.5, ref_h / 600))
        play_sz = int(72 * scale)
        side_sz = int(56 * scale)
        accent = current_accent()
        accent_hex = accent.name()
        accent_hover = accent.lighter(115).name()
        accent_pressed = accent.darker(120).name()

        # Circular play button
        play_r = play_sz * 2 // 5
        self._play_btn.setFixedSize(play_sz, play_sz)
        self._play_btn.setStyleSheet(
            f"QPushButton#playBtn{{background:{accent_hex};border-radius:{play_r}px;"
            f"min-width:{play_sz}px;min-height:{play_sz}px;"
            f"max-width:{play_sz}px;max-height:{play_sz}px;"
            f"color:#fff;border:none;font-size:{int(play_sz*0.45)}px;}}"
            f"QPushButton#playBtn:hover{{background:{accent_hover};}}"
            f"QPushButton#playBtn:pressed{{background:{accent_pressed};}}"
        )
        self._prev_btn.setFixedSize(side_sz, side_sz)
        self._next_btn.setFixedSize(side_sz, side_sz)
        accent_rgba = accent.darker(180).name()
        side_radius = side_sz * 2 // 5
        side_style = (
            f"QPushButton{{background:transparent;border:none;color:#bbbbbb;"
            f"font-size:{int(side_sz*0.42)}px;border-radius:{side_radius}px;}}"
            f"QPushButton:hover{{background:#1a1a2e;color:#fff;}}"
            f"QPushButton:pressed{{background:{accent_rgba};color:#fff;}}"
        )
        self._prev_btn.setStyleSheet(side_style)
        self._next_btn.setStyleSheet(side_style)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_sizing()

    def set_playing(self, playing: bool):
        self._is_playing = playing
        self._play_btn.setText("⏸" if playing else "▶")
