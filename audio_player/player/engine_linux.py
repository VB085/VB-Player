import re
from pathlib import Path
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from audio_player.player.engine_base import _BaseAudioEngine


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
                        'name': '默认设备 (hw:0,0)', 'driver': 'ALSA'})
    return devices


class AudioEngine(_BaseAudioEngine):
    """Linux ALSA audio engine."""

    def _default_exclusive_device(self) -> str:
        return "hw:0,0"

    def _create_sink(self) -> Gst.Element:
        if self._exclusive_mode:
            sink = Gst.ElementFactory.make("alsasink", None)
            if sink is None:
                raise RuntimeError("alsasink 不可用 — 请安装 gstreamer1.0-alsa")
            sink.set_property("device", self._exclusive_device)
        else:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
            if sink is None:
                raise RuntimeError("autoaudiosink 不可用")
        return sink

    def _output_info_dict(self) -> dict:
        if self._exclusive_mode:
            return {
                "name": self._exclusive_device,
                "driver": "ALSA (硬件直通)",
                "mode": "独占模式 (Exclusive)",
                "is_exclusive": True,
                "api": "alsa",
                "latency": "ALSA 硬件缓冲",
            }
        return {
            "name": "系统默认",
            "driver": "PipeWire / PulseAudio",
            "mode": "共享模式 (Shared)",
            "is_exclusive": False,
            "api": "pulse",
            "latency": "声音服务器控制",
        }
