from PyQt6.QtCore import (QPropertyAnimation, QEasingCurve, QPoint,
                          QSequentialAnimationGroup, QPauseAnimation,
                          QParallelAnimationGroup, pyqtProperty, QObject)
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect


def fade_in(widget: QWidget, duration: int = 300) -> QPropertyAnimation:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)
    widget.show()
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()
    return anim


def fade_out(widget: QWidget, duration: int = 300) -> QPropertyAnimation:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(widget.hide)
    anim.start()
    return anim


def slide_up(widget: QWidget, distance: int = 30, duration: int = 400) -> QPropertyAnimation:
    anim = QPropertyAnimation(widget, b"pos")
    start_y = widget.y() + distance
    anim.setDuration(duration)
    anim.setStartValue(QPoint(widget.x(), start_y))
    anim.setEndValue(widget.pos())
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()
    return anim


def slide_down(widget: QWidget, distance: int = 30, duration: int = 400) -> QPropertyAnimation:
    anim = QPropertyAnimation(widget, b"pos")
    end_y = widget.y() + distance
    anim.setDuration(duration)
    anim.setStartValue(widget.pos())
    anim.setEndValue(QPoint(widget.x(), end_y))
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(widget.hide)
    anim.start()
    return anim


def pulse(widget: QWidget, scale: float = 1.03, duration: int = 150):
    orig_geom = widget.geometry()
    center = orig_geom.center()

    def _pulse_anim(prop, start, end):
        a = QPropertyAnimation(widget, prop)
        a.setDuration(duration)
        a.setStartValue(start)
        a.setEndValue(end)
        a.setEasingCurve(QEasingCurve.Type.OutQuad)
        return a

    grow_geom = orig_geom.adjusted(
        -int(orig_geom.width() * (scale - 1) / 2),
        -int(orig_geom.height() * (scale - 1) / 2),
        int(orig_geom.width() * (scale - 1) / 2),
        int(orig_geom.height() * (scale - 1) / 2),
    )

    group = QSequentialAnimationGroup()
    group.addAnimation(_pulse_anim(b"geometry", orig_geom, grow_geom))
    group.addAnimation(_pulse_anim(b"geometry", grow_geom, orig_geom))
    group.start()
    return group
