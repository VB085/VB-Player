"""App-wide tooltip control: master switch + hover delay.

Tooltips in this app are noise by default (the UI is meant to be
self-explanatory), so they are OFF unless the user enables them
(QSettings: show_tooltips). When on, they appear only after hovering
for ~1.2s — Qt's default (~700ms) pops too eagerly.

One QApplication-level event filter does both: swallow QEvent.ToolTip
when disabled, defer QToolTip.showText through a single-shot timer when
enabled. Widgets keep calling setToolTip() as usual; this layer decides
if/when anything shows.
"""

from PyQt6.QtCore import QEvent, QObject, QTimer, QSettings
from PyQt6.QtWidgets import QToolTip

_HOVER_DELAY_MS = 1200


class TooltipGate(QObject):
    """Install once on the QApplication instance."""

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self._pending = None       # (widget, pos) awaiting the delay timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show_pending)
        app.installEventFilter(self)

    def _enabled(self) -> bool:
        return str(QSettings("VBPlayer", "VB Player").value(
            "show_tooltips", "false")).lower() == "true"

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.ToolTip:
            if not self._enabled():
                return True  # swallowed — no tooltip anywhere
            # defer: show after the hover delay, unless the cursor moves on
            self._timer.stop()
            w = self._app.widgetAt(event.globalPos())
            if w is not None:
                self._pending = (w, event.globalPos())
                self._timer.start(_HOVER_DELAY_MS)
            return True  # we own the display path
        if et in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                  QEvent.Type.MouseButtonRelease, QEvent.Type.Leave,
                  QEvent.Type.MouseButtonDblClick):
            # cursor left the spot or clicked — cancel the pending tip
            if self._timer.isActive():
                self._timer.stop()
                self._pending = None
        return False

    def _show_pending(self):
        if not self._pending or not self._enabled():
            self._pending = None
            return
        w, gpos = self._pending
        self._pending = None
        # cursor still on the same widget?
        if self._app.widgetAt(gpos) is not w:
            return
        text = w.toolTip()
        if text:
            QToolTip.showText(gpos, text, w)


_gate: TooltipGate | None = None


def install_tooltip_gate(app) -> None:
    global _gate
    if _gate is None:
        _gate = TooltipGate(app)
