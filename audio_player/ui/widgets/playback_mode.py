from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from audio_player.app import current_accent
from audio_player.i18n import _
from audio_player.player.playlist import RepeatMode


_MODES = [
    # (icon, repeat_mode, shuffle, tooltip_key)
    ("▶",     RepeatMode.Off, False, "playback.sequential"),
    ("\U0001f501", RepeatMode.All, False, "playback.repeat_all"),
    ("\U0001f502", RepeatMode.One, False, "playback.repeat_one"),
    ("\U0001f500", RepeatMode.Off, True,  "playback.shuffle_on"),
]


class PlaybackModeControl(QWidget):
    """Single button that cycles: sequential → repeat all → repeat one → shuffle."""

    repeatModeChanged = pyqtSignal(int)
    shuffleChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(52)
        self._mode_idx = 0
        self._btn = QPushButton()
        self._btn.setFixedSize(44, 36)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._cycle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self._apply_style()

    def cycle_mode(self):
        self._mode_idx = (self._mode_idx + 1) % len(_MODES)
        self._apply_style()
        _, repeat, shuffle, _ = _MODES[self._mode_idx]
        self.repeatModeChanged.emit(int(repeat))
        self.shuffleChanged.emit(shuffle)

    def _cycle(self):
        self.cycle_mode()

    def set_repeat_mode(self, mode: int):
        shuffle = self._shuffle
        for i, (_, r, s, _) in enumerate(_MODES):
            if r == RepeatMode(mode) and s == shuffle:
                self._mode_idx = i
                break
        self._apply_style()

    def set_shuffle(self, enabled: bool):
        repeat = self._repeat
        for i, (_, r, s, _) in enumerate(_MODES):
            if s == enabled and r == repeat:
                self._mode_idx = i
                break
        self._apply_style()

    @property
    def _shuffle(self) -> bool:
        return _MODES[self._mode_idx][2]

    @property
    def _repeat(self) -> RepeatMode:
        return _MODES[self._mode_idx][1]

    # ---------- theming ----------

    def _apply_style(self):
        accent = current_accent()
        ac = accent.name()
        al = accent.lighter(115).name()
        ad = accent.darker(120).name()

        icon, _rm, _shuf, tooltip_key = _MODES[self._mode_idx]
        active = self._mode_idx != 0

        if active:
            qss = (
                f"QPushButton {{"
                f"background:{ac}; color:#ffffff; border:none;"
                f"border-radius:8px; font-size:15px; }}"
                f"QPushButton:hover {{ background:{al}; }}"
                f"QPushButton:pressed {{ background:{ad}; }}"
            )
        else:
            qss = (
                f"QPushButton {{"
                f"background:transparent; color:#64748b;"
                f"border:1px solid #2a2a4a; border-radius:8px; font-size:15px; }}"
                f"QPushButton:hover {{ background:#2a2a4a; color:#cccccc; }}"
                f"QPushButton:pressed {{ background:#3a3a5a; }}"
            )

        self._btn.setText(icon)
        self._btn.setToolTip(_(tooltip_key))
        self._btn.setStyleSheet(qss)

    def _apply_style_light(self):
        accent = current_accent()
        ac = accent.name()
        al = accent.lighter(115).name()
        ad = accent.darker(120).name()

        icon, _rm, _shuf, tooltip_key = _MODES[self._mode_idx]
        active = self._mode_idx != 0

        if active:
            qss = (
                f"QPushButton {{"
                f"background:{ac}; color:#ffffff; border:none;"
                f"border-radius:8px; font-size:15px; }}"
                f"QPushButton:hover {{ background:{al}; }}"
                f"QPushButton:pressed {{ background:{ad}; }}"
            )
        else:
            qss = (
                f"QPushButton {{"
                f"background:transparent; color:#888888;"
                f"border:1px solid #d0d0d8; border-radius:8px; font-size:15px; }}"
                f"QPushButton:hover {{ background:#dcdce4; color:#555555; }}"
                f"QPushButton:pressed {{ background:#ccccd4; }}"
            )

        self._btn.setText(icon)
        self._btn.setToolTip(_(tooltip_key))
        self._btn.setStyleSheet(qss)

    def refresh_accent(self):
        self._apply_style()

    def refresh_theme_mode(self, is_light: bool):
        if is_light:
            self._apply_style_light()
        else:
            self._apply_style()

    def refresh_language(self):
        _icon, _rm, _shuf, tooltip_key = _MODES[self._mode_idx]
        self._btn.setToolTip(_(tooltip_key))
