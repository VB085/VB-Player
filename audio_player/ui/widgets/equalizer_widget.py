from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSlider,
                             QLabel, QComboBox, QPushButton, QFrame, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


STYLE = """
QSlider::groove:vertical {
    background: #252540;
    width: 4px;
    border-radius: 2px;
}
QSlider::sub-page:vertical {
    background: #7c3aed;
    border-radius: 2px;
}
QSlider::handle:vertical {
    background: #a78bfa;
    height: 10px;
    width: 10px;
    border-radius: 5px;
    margin: 0 -3px;
}
QSlider::handle:vertical:hover {
    background: #c4b5fd;
}
QComboBox {
    background: #1a1a2e;
    color: #e2e8f0;
    border: 1px solid #252540;
    border-radius: 4px;
    padding: 4px 8px;
    min-width: 120px;
}
QComboBox:hover {
    border-color: #7c3aed;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #94a3b8;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background: #1a1a2e;
    color: #e2e8f0;
    border: 1px solid #252540;
    selection-background-color: rgba(124, 58, 237, 0.3);
}
QLabel#bandLabel {
    color: #94a3b8;
    font-size: 9px;
}
QLabel#freqLabel {
    color: #64748b;
    font-size: 8px;
}
QCheckBox {
    color: #e2e8f0;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid #47476e;
    background: #1a1a2e;
}
QCheckBox::indicator:checked {
    background: #7c3aed;
    border-color: #7c3aed;
}
"""


class EqualizerWidget(QWidget):
    bandChanged = pyqtSignal(int, float)  # band index, dB value
    presetSelected = pyqtSignal(str)
    resetRequested = pyqtSignal()
    enabledToggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("equalizerWidget")
        self.setStyleSheet(STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        self._enabled_cb = QCheckBox("Equalizer")
        self._enabled_cb.toggled.connect(self.enabledToggled)
        header.addWidget(self._enabled_cb)
        header.addStretch()

        self._preset_combo = QComboBox()
        self._preset_combo.addItems([
            "Flat", "Rock", "Pop", "Classical", "Jazz",
            "Hip Hop", "Electronic", "Vocal Boost", "Bass Boost", "Treble Boost"
        ])
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        header.addWidget(self._preset_combo)

        reset_btn = QPushButton("Reset")
        reset_btn.setFixedWidth(60)
        reset_btn.clicked.connect(self.resetRequested)
        header.addWidget(reset_btn)

        layout.addLayout(header)

        # Band sliders
        bands_layout = QHBoxLayout()
        bands_layout.setSpacing(4)

        self._sliders: list[QSlider] = []
        self._value_labels: list[QLabel] = []
        freqs = [31, 62, 125, 250, 500, "1k", "2k", "4k", "8k", "16k"]

        for i, freq in enumerate(freqs):
            band_widget = QVBoxLayout()
            band_widget.setSpacing(2)

            # Value label
            val_label = QLabel("0")
            val_label.setObjectName("bandLabel")
            val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            band_widget.addWidget(val_label)

            # Slider
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-120, 120)  # -12.0 to +12.0 dB, scaled by 10
            slider.setValue(0)
            slider.setFixedWidth(28)
            slider.setMinimumHeight(100)
            slider.valueChanged.connect(lambda v, i=i: self._on_band_changed(i, v / 10.0))
            band_widget.addWidget(slider, 1, Qt.AlignmentFlag.AlignCenter)

            # Frequency label
            freq_label = QLabel(str(freq))
            freq_label.setObjectName("freqLabel")
            freq_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            band_widget.addWidget(freq_label)

            self._sliders.append(slider)
            self._value_labels.append(val_label)
            bands_layout.addLayout(band_widget)

        layout.addLayout(bands_layout)
        layout.addStretch()

    def _on_band_changed(self, band: int, db: float):
        self._value_labels[band].setText(f"{db:+.1f}")
        self.bandChanged.emit(band, db)

    def _on_preset_changed(self, name: str):
        self.presetSelected.emit(name)

    def set_band_gain(self, band: int, db: float):
        if 0 <= band < len(self._sliders):
            self._sliders[band].blockSignals(True)
            self._sliders[band].setValue(int(db * 10))
            self._sliders[band].blockSignals(False)
            self._value_labels[band].setText(f"{db:+.1f}")

    def set_all_gains(self, gains: list[float]):
        for i, g in enumerate(gains):
            if i < len(self._sliders):
                self.set_band_gain(i, g)

    def reset(self):
        for i in range(len(self._sliders)):
            self.set_band_gain(i, 0.0)
