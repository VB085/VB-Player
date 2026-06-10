from PyQt6.QtWidgets import QStackedWidget, QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, Qt


class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget with a subtle crossfade transition between pages."""

    def __init__(self, parent=None, duration: int = 150):
        super().__init__(parent)
        self._duration = duration
        self._overlay: QLabel | None = None
        self._animating = False
        self._pending_index: int | None = None

    def animate_to(self, index: int):
        if self._animating:
            self._pending_index = index
            return
        if index == self.currentIndex():
            return
        self._start_transition(index)

    def setCurrentIndex(self, index: int):
        """Override to route through animation."""
        self.animate_to(index)

    def _start_transition(self, index: int):
        self._animating = True
        old = self.currentWidget()

        # Grab screenshot of old page
        if old and old.isVisible():
            pixmap = old.grab()
            self._overlay = QLabel(self)
            self._overlay.setPixmap(pixmap)
            self._overlay.setGeometry(self.rect())
            self._overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._overlay.show()
            self._overlay.raise_()

        # Switch to new page immediately
        super().setCurrentIndex(index)

        if self._overlay:
            effect = QGraphicsOpacityEffect()
            self._overlay.setGraphicsEffect(effect)
            self._anim = QPropertyAnimation(effect, b"opacity")
            self._anim.setDuration(self._duration)
            self._anim.setStartValue(1.0)
            self._anim.setEndValue(0.0)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.finished.connect(self._on_anim_done)
            self._anim.start()
        else:
            self._animating = False
            self._process_pending()

    def _on_anim_done(self):
        if self._overlay:
            self._overlay.deleteLater()
            self._overlay = None
        self._animating = False
        self._process_pending()

    def _process_pending(self):
        if self._pending_index is not None:
            idx = self._pending_index
            self._pending_index = None
            self.animate_to(idx)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay:
            self._overlay.setGeometry(self.rect())
