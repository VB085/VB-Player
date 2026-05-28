"""Tests for PlaybackState enum."""

from audio_player.player._types import PlaybackState


def test_states_have_expected_values():
    assert PlaybackState.Stopped == 0
    assert PlaybackState.Playing == 1
    assert PlaybackState.Paused == 2


def test_states_are_int_enum():
    assert isinstance(PlaybackState.Stopped, int)
    assert int(PlaybackState.Playing) == 1


def test_comparison():
    assert PlaybackState.Playing > PlaybackState.Stopped
    assert PlaybackState.Paused > PlaybackState.Stopped
    assert PlaybackState.Playing != PlaybackState.Paused
