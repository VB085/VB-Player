from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QLabel
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from audio_player.app import current_accent


def _format_time(ms: int) -> str:
    if ms < 0:
        ms = 0
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class SeekSlider(QWidget):
    seekRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0
        self._dragging = False
        self._ui_radius = 12
        self._last_sizing_height = 0  # avoid redundant setStyleSheet on resize

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)

        self._current_label = QLabel("0:00")
        self._current_label.setMinimumWidth(46)
        layout.addWidget(self._current_label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.sliderPressed.connect(self._on_press)
        self._slider.sliderReleased.connect(self._on_release)
        layout.addWidget(self._slider, 1)

        self._duration_label = QLabel("0:00")
        self._duration_label.setMinimumWidth(46)
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._duration_label)

        self._apply_sizing()

    def _apply_sizing(self, ui_radius: int = None):
        if ui_radius is not None:
            self._ui_radius = ui_radius
        ur = self._ui_radius
        h = max(self.height(), 24)
        fs = max(10, min(13, int(h * 0.35)))
        self._current_label.setStyleSheet(
            f"color:#94a3b8;font-size:{fs}px;font-family:monospace;")
        self._duration_label.setStyleSheet(
            f"color:#94a3b8;font-size:{fs}px;font-family:monospace;")
        accent = current_accent()
        accent_hex = accent.name()
        accent_light = accent.lighter(130).name()
        accent_bright = accent.lighter(160).name()
        groove_h = max(3, h // 10)
        # Capsule handle parallel to horizontal groove: wider than tall
        hw = max(8, ur // 2 + 4)
        hh = max(16, ur + 8)
        br = hw // 2
        self._slider.setStyleSheet(
            f"QSlider::groove:horizontal{{background:#252540;height:{groove_h}px;border-radius:{groove_h//2}px;}}"
            f"QSlider::sub-page:horizontal{{background:{accent_hex};border-radius:{groove_h//2}px;}}"
            f"QSlider::handle:horizontal{{background:{accent_light};width:{hh}px;height:{hw}px;"
            f"border-radius:{br}px;margin:-{hw//2}px 0;}}"
            f"QSlider::handle:horizontal:hover{{background:{accent_bright};}}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Only re-apply stylesheet when height actually changes
        # (width changes during window resize don't affect the slider style)
        h = self.height()
        if h != self._last_sizing_height:
            self._last_sizing_height = h
            self._apply_sizing()

    def set_position(self, ms: int):
        if not self._dragging:
            self._slider.blockSignals(True)
            self._slider.setValue(ms)
            self._slider.blockSignals(False)
            self._current_label.setText(_format_time(ms))

    def set_duration(self, ms: int):
        self._duration = ms
        self._slider.setRange(0, ms if ms > 0 else 1)
        self._duration_label.setText(_format_time(ms))

    def _on_press(self):
        self._dragging = True

    def _on_release(self):
        self._dragging = False
        ms = self._slider.value()
        self._current_label.setText(_format_time(ms))
        self.seekRequested.emit(ms)
