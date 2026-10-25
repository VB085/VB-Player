"""Startup loading overlay — covers the content area while the library
loads. Sidebar/title bar stay interactive (the overlay is parented to the
content stack only).

Visual language matches EmptyStateWidget (accent circle + title + hint)
plus the bluetooth-card 8px accent progress bar. Shows only after a 400ms
delay (small libraries never flash it) and fades out in 200ms.
"""

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QGraphicsOpacityEffect
from PyQt6.QtGui import QPainter, QColor

from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _
from audio_player.ui.icons import _icon

_SHOW_DELAY_MS = 400
_FADE_MS = 200
_BIG_LIBRARY = 40   # below this track count, don't bother showing


class LoadingOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("loadingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._done = 0
        self._total = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        circle = QLabel()
        circle.setFixedSize(64, 64)
        circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        accent = current_accent()
        circle.setStyleSheet(
            f"background:rgba({accent.red()},{accent.green()},{accent.blue()},0.10);"
            f"border-radius:32px;")
        circle.setPixmap(_icon("fa6s.music", color="#777").pixmap(26, 26))
        lay.addWidget(circle, 0, Qt.AlignmentFlag.AlignCenter)

        self._title = QLabel(_("loading.title"))
        self._title.setObjectName("emptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._title)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedWidth(260)
        self._bar.setFixedHeight(8)
        self._style_bar()
        lay.addWidget(self._bar, 0, Qt.AlignmentFlag.AlignCenter)

        self._count = QLabel("0 / 0")
        self._count.setObjectName("emptyHint")
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._count)

        # delayed show + fade-out machinery
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(_SHOW_DELAY_MS)
        self._show_timer.timeout.connect(self._show_now)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity")
        self._fade.setDuration(_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self.hide)
        self.hide()

    def _style_bar(self):
        accent = current_accent()
        self._bar.setStyleSheet(
            f"QProgressBar{{background:#0fffffff;border:none;border-radius:4px;}}"
            f"QProgressBar::chunk{{background:{accent.name()};border-radius:4px;}}")

    def arm(self, done: int, total: int):
        """Called on progress; starts the delayed show for big libraries."""
        self._done, self._total = done, total
        self._update_progress()
        if total >= _BIG_LIBRARY and not self.isVisible() and not self._show_timer.isActive():
            self._show_timer.start()

    def set_progress(self, done: int, total: int):
        self._done, self._total = done, total
        self._update_progress()

    def _update_progress(self):
        self._count.setText(_("loading.count", done=self._done, total=self._total))
        self._bar.setMaximum(max(1, self._total))
        self._bar.setValue(self._done)

    def _show_now(self):
        if self._done >= self._total:   # finished before the delay elapsed
            return
        self.setGeometry(self.parentWidget().rect())
        self._effect.setOpacity(1.0)
        self.show()
        self.raise_()

    def finish(self):
        """Done — cancel pending show, or fade out if visible."""
        self._show_timer.stop()
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def refresh_accent(self):
        self._style_bar()

    def paintEvent(self, event):
        p = QPainter(self)
        is_light = current_theme_mode() == "light"
        base = QColor(245, 245, 245, 247) if is_light else QColor(24, 24, 27, 250)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)
        p.end()
