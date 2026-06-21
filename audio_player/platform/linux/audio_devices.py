"""Unified audio device enumeration — local, wired, Bluetooth, network."""

import subprocess
import json
from dataclasses import dataclass, field
from typing import Optional


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
    """Get ALSA hardware devices for exclusive mode."""
    devices = []
    try:
        result = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.split("\n"):
            if not line.startswith("card"):
                continue
            # e.g., "card 0: PCH [HDA Intel PCH], device 0: ALC255 Analog [ALC255 Analog]"
            parts = line.split(":", 1)
            if len(parts) < 2:
                continue
            card_part = parts[0].strip()  # "card 0"
            desc_part = parts[1].strip()  # "PCH [HDA Intel PCH], device 0: ..."

            card_num = card_part.replace("card", "").strip()

            # Parse device number and name
            import re
            m = re.match(r'(.*?), device (\d+):\s*(.*)', desc_part)
            if m:
                card_name = m.group(1).strip()
                dev_num = m.group(2)
                dev_desc = m.group(3).strip()
                hw_id = f"hw:{card_num},{dev_num}"
                devices.append(AudioDevice(
                    id=hw_id,
                    name=f"{card_name} ({hw_id})",
                    device_type="wired",
                    description=dev_desc,
                    available=False,  # only available when exclusive mode on
                ))
    except Exception:
        pass
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
