"""Tests for locale-independent ALSA device naming."""

from audio_player.platform.linux.alsa_hw import _parse_cards, _parse_pcm

CARDS = """
 0 [NVidia         ]: HDA-Intel - HDA NVidia
                      HDA NVidia at 0x92080000 irq 17
 1 [Pro            ]: USB-Audio - Tone2 Pro
                      Tone2 Pro at usb-0000:00:14.0-1
 2 [sofhdadsp      ]: sof-hda-dsp - sof-hda-dsp
                      Alienware-Alienwarex15R2
"""

PCM = """
00-03: HDMI 0 : HDMI 0 : playback 1
00-07: HDMI 1 : HDMI 1 : playback 1
01-00: USB Audio : USB Audio : playback 1
02-00: HDA Analog (*) :  : playback 1 : capture 1
02-03: HDMI1 (*) : HDMI 1 : playback 1
02-06: DMIC (*) :  : capture 1
02-31: HDA Analog Deep Buffer (*) :  : playback 1
"""


def test_card_models_use_the_driver_description():
    cards = _parse_cards(CARDS)
    assert cards[0] == ("NVidia", "HDA NVidia")
    assert cards[1] == ("Pro", "Tone2 Pro")
    assert cards[2] == ("sofhdadsp", "sof-hda-dsp")


def test_pcm_names_are_human_readable():
    devices = _parse_pcm(PCM, _parse_cards(CARDS))
    by_hw = {d["hw"]: d for d in devices}

    assert by_hw["hw:0,3"]["name"] == "HDA NVidia · HDMI 0 (hw:0,3)"
    assert by_hw["hw:0,7"]["name"] == "HDA NVidia · HDMI 1 (hw:0,7)"
    assert by_hw["hw:1,0"]["name"] == "Tone2 Pro · USB Audio (hw:1,0)"
    assert by_hw["hw:2,0"]["name"] == "sof-hda-dsp · HDA Analog (hw:2,0)"
    assert by_hw["hw:2,3"]["name"] == "sof-hda-dsp · HDMI 1 (hw:2,3)"
    assert by_hw["hw:2,31"]["name"] == "sof-hda-dsp · HDA Analog Deep Buffer (hw:2,31)"


def test_capture_only_devices_are_skipped():
    devices = _parse_pcm(PCM, _parse_cards(CARDS))
    assert all(d["device"] != 6 for d in devices)
    assert len(devices) == 6
