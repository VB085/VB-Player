from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSlider, QLabel
from PyQt6.QtCore import Qt, pyqtSignal
from audio_player.app import current_accent


def _make_style(ui_radius: int = 12) -> str:
    accent = current_accent()
    # Capsule handle parallel to vertical groove: taller than wide
    hw = max(8, ui_radius // 2 + 4)
    hh = max(16, ui_radius + 8)
    br = hw // 2
    return (
        f"QSlider::groove:vertical{{background:#252540;width:4px;border-radius:2px;}}"
        f"QSlider::sub-page:vertical{{background:#1a1a2e;border-radius:2px;}}"
        f"QSlider::add-page:vertical{{background:{accent.name()};border-radius:2px;}}"
        f"QSlider::handle:vertical{{background:{accent.lighter(130).name()};"
        f"width:{hw}px;height:{hh}px;border-radius:{br}px;margin:0 -{hw//2}px;}}"
        f"QSlider::handle:vertical:hover{{background:{accent.lighter(160).name()};}}"
        f"QLabel{{color:#94a3b8;font-size:10px;}}"
    )


class VolumeControl(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(52)
        self._ui_radius = 12
        self._refresh_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)

        self._label = QLabel("\U0001f50a")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._slider = QSlider(Qt.Orientation.Vertical)
        self._slider.setRange(0, 100)
        self._slider.setValue(80)
        self._slider.setFixedHeight(100)
        self._slider.setFixedWidth(48)
        self._slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self._slider, 0, Qt.AlignmentFlag.AlignCenter)

        self._pct_label = QLabel("80%")
        self._pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._pct_label)

    def set_value(self, value: float):
        pct = int(value * 100)
        self._slider.blockSignals(True)
        self._slider.setValue(pct)
        self._slider.blockSignals(False)
        self._pct_label.setText(f"{pct}%")
        self._update_icon(pct)

    def _on_slider(self, value):
        pct = value / 100.0
        self._pct_label.setText(f"{value}%")
        self._update_icon(value)
        self.valueChanged.emit(pct)

    def _update_icon(self, pct):
        if pct == 0:
            self._label.setText("\U0001f507")
        elif pct < 33:
            self._label.setText("\U0001f508")
        elif pct < 66:
            self._label.setText("\U0001f509")
        else:
            self._label.setText("\U0001f50a")

    def _refresh_style(self, ui_radius: int = None):
        if ui_radius is not None:
            self._ui_radius = ui_radius
        self.setStyleSheet(_make_style(self._ui_radius))
