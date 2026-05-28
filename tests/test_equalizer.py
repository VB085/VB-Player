"""Tests for EqualizerManager."""

import pytest
from audio_player.player.equalizer import EqualizerManager, PRESETS, BAND_FREQUENCIES


@pytest.fixture
def eq(qapp):
    return EqualizerManager()


def test_initial_state(eq):
    assert eq.enabled is False
    assert eq.current_preset == "Flat"
    assert eq.all_gains() == [0.0] * 10


def test_band_count():
    assert EqualizerManager.BAND_COUNT == 10
    assert len(BAND_FREQUENCIES) == 10


def test_set_band_gain(eq):
    eq.set_band_gain(0, 5.0)
    assert eq.band_gain(0) == 5.0


def test_set_band_gain_clamping(eq):
    eq.set_band_gain(0, 20.0)
    assert eq.band_gain(0) == 12.0
    eq.set_band_gain(0, -20.0)
    assert eq.band_gain(0) == -12.0


def test_set_band_gain_out_of_range(eq):
    eq.set_band_gain(-1, 5.0)  # should not raise
    eq.set_band_gain(10, 5.0)  # should not raise
    assert eq.band_gain(-1) == 0.0
    assert eq.band_gain(10) == 0.0


def test_set_all_gains(eq):
    gains = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    eq.set_all_gains(gains)
    assert eq.all_gains() == gains


def test_set_all_gains_truncates(eq):
    eq.set_all_gains([1.0, 2.0, 3.0])  # only 3 of 10
    gains = eq.all_gains()
    assert gains[0] == 1.0
    assert gains[2] == 3.0
    assert gains[3] == 0.0  # untouched


def test_reset_flat(eq):
    eq.set_band_gain(0, 5.0)
    eq.reset_flat()
    assert eq.all_gains() == [0.0] * 10
    assert eq.current_preset == "Flat"


def test_apply_preset(eq):
    eq.apply_preset("Rock")
    assert eq.current_preset == "Rock"
    assert eq.all_gains() == PRESETS["Rock"].gains


def test_apply_preset_unknown(eq):
    eq.apply_preset("Nonexistent")
    assert eq.current_preset == "Flat"  # unchanged


def test_enabled_property(eq):
    eq.enabled = True
    assert eq.enabled is True
    eq.enabled = False
    assert eq.enabled is False


def test_presets_all_have_10_bands():
    for name, preset in PRESETS.items():
        assert len(preset.gains) == 10, f"Preset {name} has {len(preset.gains)} bands"


def test_presets_gain_range():
    for name, preset in PRESETS.items():
        for g in preset.gains:
            assert -12.0 <= g <= 12.0, f"Preset {name} has out-of-range gain {g}"
