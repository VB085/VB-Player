import re
from pathlib import Path
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from audio_player.player.engine_base import _BaseAudioEngine
from audio_player.i18n import _


def enumerate_hw_devices() -> list[dict]:
    """Return list of {card, device, hw, name} for ALSA hardware playback devices."""
    devices = []
    card_names: dict[int, str] = {}
    try:
        for line in Path('/proc/asound/cards').read_text().splitlines():
            m = re.match(r'\s*(\d+)\s*\[([^\]]+)\]\s*:\s*(.+)', line)
            if m:
                card_names[int(m.group(1))] = m.group(2).strip()
    except OSError:
        pass

    sound_dir = Path('/sys/class/sound')
    if sound_dir.exists():
        for entry in sorted(sound_dir.iterdir()):
            m = re.match(r'pcmC(\d+)D(\d+)p', entry.name)
            if m:
                card, dev = int(m.group(1)), int(m.group(2))
                hw = f'hw:{card},{dev}'
                name = card_names.get(card, f'Card {card}')
                devices.append({'card': card, 'device': dev, 'hw': hw,
                                'name': f'{name} ({hw})', 'driver': 'ALSA'})
    if not devices:
        for card_id, name in sorted(card_names.items()):
            hw = f'hw:{card_id},0'
            devices.append({'card': card_id, 'device': 0, 'hw': hw,
                            'name': f'{name} ({hw})', 'driver': 'ALSA'})
    if not devices:
        devices.append({'card': 0, 'device': 0, 'hw': 'hw:0,0',
                        'name': 'hw:0,0', 'driver': 'ALSA'})
    return devices


class AudioEngine(_BaseAudioEngine):
    """Linux ALSA audio engine."""

    def _default_exclusive_device(self) -> str:
        return "hw:0,0"

    def _create_sink(self) -> Gst.Element:
        if self._exclusive_mode:
            sink = Gst.ElementFactory.make("alsasink", None)
            if sink is None:
                raise RuntimeError(_("engine.alsa_unavailable"))
            sink.set_property("device", self._exclusive_device)
        else:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
            if sink is None:
                raise RuntimeError(_("engine.auto_unavailable"))
        return sink

    def _output_info_dict(self) -> dict:
        if self._exclusive_mode:
            return {
                "name": self._exclusive_device,
                "driver": _("engine.alsa_driver"),
                "mode": _("engine.exclusive_mode"),
                "is_exclusive": True,
                "api": "alsa",
                "latency": _("engine.alsa_buffer"),
            }
        return {
            "name": _("output.system_default"),
            "driver": "PipeWire / PulseAudio",
            "mode": _("engine.shared_mode"),
            "is_exclusive": False,
            "api": "pulse",
            "latency": _("engine.sound_server"),
        }
