from PyQt6.QtCore import QObject
from dataclasses import dataclass


@dataclass
class EqPreset:
    name: str
    gains: list[float]  # dB values for 10 bands


PRESETS = {
    "Flat": EqPreset("Flat", [0.0] * 10),
    "Rock": EqPreset("Rock", [4.0, 2.0, -1.0, -2.0, -1.0, 2.0, 5.0, 6.0, 5.0, 4.0]),
    "Pop": EqPreset("Pop", [-1.0, 1.0, 3.0, 2.0, -1.0, -1.0, 0.0, 2.0, 3.0, 2.0]),
    "Classical": EqPreset("Classical", [3.0, 2.0, 0.0, -1.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0]),
    "Jazz": EqPreset("Jazz", [3.0, 1.0, -1.0, -2.0, 0.0, 2.0, 3.0, 2.0, 1.0, 1.0]),
    "Hip Hop": EqPreset("Hip Hop", [5.0, 4.0, 1.0, 0.0, -1.0, 0.0, 2.0, 3.0, 3.0, 2.0]),
    "Electronic": EqPreset("Electronic", [4.0, 2.0, -2.0, -3.0, -2.0, 2.0, 4.0, 5.0, 4.0, 3.0]),
    "Vocal Boost": EqPreset("Vocal Boost", [-2.0, -2.0, -1.0, 2.0, 4.0, 3.0, 1.0, 0.0, -1.0, -2.0]),
    "Bass Boost": EqPreset("Bass Boost", [6.0, 5.0, 2.0, 0.0, -1.0, -2.0, -2.0, -1.0, 0.0, 0.0]),
    "Treble Boost": EqPreset("Treble Boost", [-2.0, -2.0, -1.0, 0.0, 0.0, 1.0, 3.0, 5.0, 6.0, 6.0]),
}

BAND_FREQUENCIES = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


class EqualizerManager(QObject):
    BAND_COUNT = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gains = [0.0] * self.BAND_COUNT
        self._enabled = False
        self._current_preset = "Flat"

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val

    def set_band_gain(self, band: int, db: float):
        if 0 <= band < self.BAND_COUNT:
            self._gains[band] = max(-12.0, min(12.0, db))

    def band_gain(self, band: int) -> float:
        if 0 <= band < self.BAND_COUNT:
            return self._gains[band]
        return 0.0

    def all_gains(self) -> list[float]:
        return list(self._gains)

    def set_all_gains(self, gains: list[float]):
        for i, g in enumerate(gains[:self.BAND_COUNT]):
            self.set_band_gain(i, g)

    def reset_flat(self):
        self._gains = [0.0] * self.BAND_COUNT
        self._current_preset = "Flat"

    @property
    def current_preset(self) -> str:
        return self._current_preset

    def apply_preset(self, preset_name: str):
        preset = PRESETS.get(preset_name)
        if preset:
            self._current_preset = preset_name
            self.set_all_gains(preset.gains)

    @property
    def presets(self) -> dict:
        return PRESETS
