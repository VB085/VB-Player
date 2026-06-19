from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSlider,
                             QLabel, QComboBox, QPushButton, QFrame, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from audio_player.app import current_theme_mode


class _NoWheelSlider(QSlider):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, e):
        e.ignore()


class _NoWheelComboBox(QComboBox):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, e):
        e.ignore()


def _build_eq_style() -> str:
    """Build equalizer QSS based on current theme mode."""
    is_light = current_theme_mode() == "light"
    bg = "#e8e8e8" if is_light else "#1a1a2e"
    fg = "#333333" if is_light else "#e2e8f0"
    border = "#d0d0d0" if is_light else "#252540"
    groove = "#d0d0d0" if is_light else "#252540"
    label = "#666666" if is_light else "#94a3b8"
    freq = "#888888" if is_light else "#64748b"
    cb_border = "#cccccc" if is_light else "#47476e"
    return """
QSlider::groove:vertical {{
    background: {groove};
    width: 4px;
    border-radius: 2px;
}}
QSlider::sub-page:vertical {{
    background: #7c3aed;
    border-radius: 2px;
}}
QSlider::handle:vertical {{
    background: #a78bfa;
    height: 10px;
    width: 10px;
    border-radius: 5px;
    margin: 0 -3px;
}}
QSlider::handle:vertical:hover {{
    background: #c4b5fd;
}}
QComboBox {{
    background: {bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px 8px;
    min-width: 120px;
}}
QComboBox:hover {{
    border-color: #7c3aed;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {label};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {bg};
    color: {fg};
    border: 1px solid {border};
    selection-background-color: #2e185e;
}}
QLabel#bandLabel {{
    color: {label};
    font-size: 9px;
}}
QLabel#freqLabel {{
    color: {freq};
    font-size: 8px;
}}
QCheckBox {{
    color: {fg};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid {cb_border};
    background: {bg};
}}
QCheckBox::indicator:checked {{
    background: #7c3aed;
    border-color: #7c3aed;
}}
""".format(bg=bg, fg=fg, border=border, groove=groove, label=label, freq=freq, cb_border=cb_border)


class EqualizerWidget(QWidget):
    bandChanged = pyqtSignal(int, float)  # band index, dB value
    presetSelected = pyqtSignal(str)
    resetRequested = pyqtSignal()
    enabledToggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("equalizerWidget")
        self.setStyleSheet(_build_eq_style())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        self._enabled_cb = QCheckBox("Equalizer")
        self._enabled_cb.toggled.connect(self.enabledToggled)
        header.addWidget(self._enabled_cb)
        header.addStretch()

        self._preset_combo = _NoWheelComboBox()
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
            slider = _NoWheelSlider(Qt.Orientation.Vertical)
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

    def refresh_theme_mode(self, is_light: bool):
        """Rebuild QSS when theme changes."""
        self.setStyleSheet(_build_eq_style())
