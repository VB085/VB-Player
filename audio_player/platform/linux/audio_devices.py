"""Unified audio device enumeration — local, wired, Bluetooth, network."""

import subprocess
import json
from dataclasses import dataclass, field
from typing import Optional

from audio_player.platform.linux.alsa_hw import enumerate_alsa_playback_devices


@dataclass
class AudioDevice:
    id: str                        # "local", "hw:1,0", "bt:XX:XX", "cast:xxx"
    name: str
    device_type: str = "local"     # local, wired, bluetooth, network
    description: str = ""          # extra info line
    available: bool = True         # selectable right now
    active: bool = False           # currently in use
    codec: str = ""
    sample_rate: str = ""
    detail: str = ""               # tooltip detail


def get_wired_devices() -> list[AudioDevice]:
    """Get wired audio sinks from PipeWire/PulseAudio."""
    devices = []
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sinks"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            sinks = json.loads(result.stdout)
            for s in sinks:
                name = s.get("description", s.get("name", "Unknown"))
                dev = AudioDevice(
                    id=f"pw:{s.get('name', '')}",
                    name=name,
                    device_type="wired",
                    description=s.get("properties", {}).get("alsa.card_name", ""),
                    available=True,
                )
                # Active sample rate
                spec = s.get("sample_spec", {})
                if spec:
                    dev.sample_rate = spec.get("rate", "")
                devices.append(dev)
    except Exception:
        pass
    return devices


def get_alsa_hw_devices() -> list[AudioDevice]:
    """Get ALSA hardware devices with per-PCM names (HDA Analog, HDMI 1, ...)."""
    devices = []
    for dev in enumerate_alsa_playback_devices():
        devices.append(AudioDevice(
            id=dev["hw"],
            name=dev["name"],
            device_type="wired",
            description=dev.get("description", ""),
            available=False,  # only available when exclusive mode on
        ))
    return devices


def get_local_device(active: bool = True) -> AudioDevice:
    return AudioDevice(
        id="local",
        name="本地播放",
        device_type="local",
        description="PipeWire/PulseAudio 共享模式",
        available=True,
        active=active,
    )
