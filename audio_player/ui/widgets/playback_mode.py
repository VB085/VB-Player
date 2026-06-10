from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from audio_player.app import current_accent
from audio_player.i18n import _
from audio_player.player.playlist import RepeatMode
from audio_player.ui.icons import (
    MODE_SEQUENTIAL, MODE_REPEAT_ALL, MODE_REPEAT_ONE, MODE_SHUFFLE, MODE_MORE,
    _icon,
)


_MODES = [
    # (icon_name, repeat_mode, shuffle, tooltip_key)
    (MODE_SEQUENTIAL, RepeatMode.Off, False, "playback.sequential"),
    (MODE_REPEAT_ALL, RepeatMode.All, False, "playback.repeat_all"),
    (MODE_REPEAT_ONE, RepeatMode.One, False, "playback.repeat_one"),
    (MODE_SHUFFLE,    RepeatMode.Off, True,  "playback.shuffle_on"),
]


class PlaybackModeControl(QWidget):
    """Single button that cycles: sequential → repeat all → repeat one → shuffle.
    Below it: expand and 'more options' buttons."""

    repeatModeChanged = pyqtSignal(int)
    shuffleChanged = pyqtSignal(bool)
    moreClicked = pyqtSignal()
    expandRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(52)
        self._mode_idx = 0
        self._btn = QPushButton()
        self._btn.setFixedSize(44, 36)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._cycle)

        self._expand_btn = QPushButton()
        self._expand_btn.setIcon(_icon("fa6s.up-right-and-down-left-from-center", color="#64748b"))
        self._expand_btn.setFixedSize(44, 36)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._expand_btn.setToolTip(_("transport.expand"))
        self._expand_btn.clicked.connect(self.expandRequested)

        self._more_btn = QPushButton()
        self._more_btn.setIcon(_icon(MODE_MORE, color="#64748b"))
        self._more_btn.setFixedSize(44, 36)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setToolTip("⋯")
        self._more_btn.clicked.connect(self.moreClicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(4)
        layout.addWidget(self._expand_btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._more_btn, 0, Qt.AlignmentFlag.AlignCenter)
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

        icon_name, _rm, _shuf, tooltip_key = _MODES[self._mode_idx]
        active = self._mode_idx != 0

        icon_color = "#ffffff" if active else "#64748b"
        self._btn.setIcon(_icon(icon_name, color=icon_color))

        if active:
            qss = (
                f"QPushButton {{"
                f"background:{ac}; border:none;"
                f"border-radius:8px; }}"
                f"QPushButton:hover {{ background:{al}; }}"
                f"QPushButton:pressed {{ background:{ad}; }}"
            )
        else:
            qss = (
                f"QPushButton {{"
                f"background:transparent;"
                f"border:1px solid #2a2a4a; border-radius:8px; }}"
                f"QPushButton:hover {{ background:#2a2a4a; }}"
                f"QPushButton:pressed {{ background:{ad}; }}"
            )

        self._btn.setToolTip(_(tooltip_key))
        self._btn.setStyleSheet(qss)

        # Expand button — same border style
        self._expand_btn.setStyleSheet(
            f"QPushButton{{background:transparent;"
            f"border:1px solid #2a2a4a;border-radius:8px;}}"
            f"QPushButton:hover{{background:#2a2a4a;}}"
            f"QPushButton:pressed{{background:{ad};}}"
        )

        # More button — same border style, accent pressed
        self._more_btn.setStyleSheet(
            f"QPushButton{{background:transparent;"
            f"border:1px solid #2a2a4a;border-radius:8px;}}"
            f"QPushButton:hover{{background:#2a2a4a;}}"
            f"QPushButton:pressed{{background:{ad};}}"
        )

    def _apply_style_light(self):
        accent = current_accent()
        ac = accent.name()
        al = accent.lighter(115).name()
        ad = accent.darker(120).name()

        icon_name, _rm, _shuf, tooltip_key = _MODES[self._mode_idx]
        active = self._mode_idx != 0

        icon_color = "#ffffff" if active else "#888888"
        self._btn.setIcon(_icon(icon_name, color=icon_color))

        if active:
            qss = (
                f"QPushButton {{"
                f"background:{ac}; border:none;"
                f"border-radius:8px; }}"
                f"QPushButton:hover {{ background:{al}; }}"
                f"QPushButton:pressed {{ background:{ad}; }}"
            )
        else:
            qss = (
                f"QPushButton {{"
                f"background:transparent;"
                f"border:1px solid #d0d0d8; border-radius:8px; }}"
                f"QPushButton:hover {{ background:#dcdce4; }}"
                f"QPushButton:pressed {{ background:{ad}; }}"
            )

        self._btn.setToolTip(_(tooltip_key))
        self._btn.setStyleSheet(qss)

        # Expand button — light variant
        self._expand_btn.setStyleSheet(
            f"QPushButton{{background:transparent;"
            f"border:1px solid #d0d0d8;border-radius:8px;}}"
            f"QPushButton:hover{{background:#dcdce4;}}"
            f"QPushButton:pressed{{background:{ad};}}"
        )

        # More button — light variant
        self._more_btn.setStyleSheet(
            f"QPushButton{{background:transparent;"
            f"border:1px solid #d0d0d8;border-radius:8px;}}"
            f"QPushButton:hover{{background:#dcdce4;}}"
            f"QPushButton:pressed{{background:{ad};}}"
        )

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
