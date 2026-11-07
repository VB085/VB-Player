"""Tests for bit-perfect passthrough and URL pipeline selection."""

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from audio_player.player.engine import AudioEngine


def _engine(qapp):
    return AudioEngine()


def test_bit_perfect_implies_exclusive_and_unity_volume(qapp):
    engine = _engine(qapp)
    engine.volume = 0.35
    engine.bit_perfect_mode = True

    assert engine.bit_perfect_mode is True
    assert engine.exclusive_mode is True
    assert engine.volume == 1.0
    assert engine._bit_perfect_active() is True
    engine.stop()


def test_bit_perfect_bypass_chain_omits_dsp(qapp):
    engine = _engine(qapp)
    engine.exclusive_mode = True
    engine.bit_perfect_mode = True

    pipeline, elems = engine._create_audio_pipeline(
        "bypass-test", "/tmp/does-not-exist.flac", lambda *a: None
    )
    filesrc, decodebin, queue, conv1, resample1, rgvolume, volume, eq, conv2, resample2, sink = elems

    assert resample1 is None
    assert rgvolume is None
    assert volume is None
    assert eq is None
    assert conv2 is None
    assert resample2 is None
    assert sink is not None
    pipeline.set_state(Gst.State.NULL)
    engine.stop()


def test_standard_chain_keeps_dsp(qapp):
    engine = _engine(qapp)
    pipeline, elems = engine._create_audio_pipeline(
        "standard-test", "/tmp/does-not-exist.flac", lambda *a: None
    )
    *_, volume, eq, conv2, resample2, sink = elems

    assert volume is not None
    assert eq is not None
    assert conv2 is not None
    assert resample2 is not None
    assert sink is not None
    pipeline.set_state(Gst.State.NULL)
    engine.stop()


def test_volume_change_exits_bit_perfect(qapp):
    engine = _engine(qapp)
    engine.bit_perfect_mode = True

    engine.volume = 0.5

    assert engine.bit_perfect_mode is False
    assert engine.volume == 0.5
    engine.stop()


def test_enabling_eq_exits_bit_perfect(qapp):
    engine = _engine(qapp)
    engine.bit_perfect_mode = True

    engine.set_eq_enabled(True)

    assert engine.bit_perfect_mode is False
    engine.stop()


def test_url_pipeline_uses_exclusive_sink(qapp):
    engine = _engine(qapp)
    engine.exclusive_mode = True
    engine.bit_perfect_mode = True

    engine._build_url_pipeline("http://127.0.0.1:9/stream.flac")

    playbin = engine._playbin
    assert playbin is not None
    assert playbin.get_property("audio-sink") is not None
    assert playbin.get_property("volume") == 1.0
    engine.stop()
