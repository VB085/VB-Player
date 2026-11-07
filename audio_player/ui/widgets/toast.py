"""Bottom-center toast: a message plus an optional 撤销 action.

One instance lives on the MainWindow; show_toast() restarts its timer.
Fades in 150 ms, holds 5 s, fades out 250 ms. Never modal — it floats
above the content and ignores clicks except on the action button.
"""

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton,
                             QGraphicsOpacityEffect)

from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _

_HOLD_MS = 5000


class Toast(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(14)
        self._label = QLabel("")
        self._label.setObjectName("toastLabel")
        lay.addWidget(self._label)
        self._action = QPushButton(_("toast.undo"))
        self._action.setObjectName("toastAction")
        self._action.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action.clicked.connect(self._on_action)
        lay.addWidget(self._action)
        lay.addStretch(0)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_HOLD_MS)
        self._timer.timeout.connect(self._fade_out)
        self._anim = QPropertyAnimation(self._effect, b"opacity")
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_done)
        self._on_action_cb = None
        self.hide()

    def _style(self):
        accent = current_accent()
        is_light = current_theme_mode() == "light"
        bg = "rgba(250,250,250,0.97)" if is_light else "rgba(32,32,36,0.97)"
        fg = "#1a1a1a" if is_light else "#eee"
        self.setStyleSheet(
            f"QWidget#toast {{ background: {bg}; border-radius: 10px; }}"
            f"QLabel#toastLabel {{ color: {fg}; font-size: 12px; background: transparent; }}"
            f"QPushButton#toastAction {{ background: transparent; color: {accent.name()};"
            f"border: none; font-size: 12px; font-weight: bold; padding: 2px 6px; }}"
            f"QPushButton#toastAction:hover {{ color: {accent.lighter(120).name()}; }}")

    def show_toast(self, text: str, on_action=None, action_text: str | None = None):
        self._style()
        self._label.setText(text)
        self._on_action_cb = on_action
        self._action.setVisible(on_action is not None)
        if action_text:
            self._action.setText(action_text)
        self._reposition()
        self._effect.setOpacity(0.0)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start()

    def _reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 72   # above the pill/bar zone
        self.move(max(8, x), max(8, y))

    def _on_action(self):
        cb = self._on_action_cb
        self._on_action_cb = None
        self._timer.stop()
        self._fade_out()
        if cb:
            cb()

    def _fade_out(self):
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_done(self):
        if self._effect.opacity() < 0.05:
            self.hide()
