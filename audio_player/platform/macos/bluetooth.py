"""macOS Bluetooth audio device info via IOBluetooth / system_profiler.

Provides the same BluetoothDevice / get_bluetooth_devices / get_host_codecs /
get_device_codecs API as the Linux BlueZ implementation and the Windows
WASAPI implementation, so NetworkPage can import uniformly.

Detection strategy:
  1. system_profiler SPBluetoothDataType --json (no pyobjc dependency)
  2. IOBluetoothDevice via pyobjc (optional, richer data)
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

_HAS_OBJC = False
if sys.platform == "darwin":
    try:
        import IOBluetooth
        _HAS_OBJC = True
    except ImportError:
        pass

# Codec identifiers used by macOS
_CODEC_MAP = {
    0: "SBC",
    2: "AAC",
    255: "Vendor",
}


@dataclass
class BluetoothDevice:
    """Bluetooth audio device descriptor. Same fields as Linux/Windows."""
    name: str = ""
    address: str = ""
    icon: str = "audio-card"
    connected: bool = False
    paired: bool = False
    codec: str = ""
    codec_id: int = 0
    frequency: str = ""
    bitpool_min: int = 0
    bitpool_max: int = 0
    channels: str = ""
    state: str = "active"
    volume: int = 0
    battery: Optional[int] = None
    device_class: int = 0

    @property
    def bitrate(self) -> str:
        if self.codec in ("SBC", "SBC XQ"):
            return "~551 kbps" if self.bitpool_max >= 53 else f"~{self.bitpool_max * 10} kbps"
        if self.codec == "AAC": return "~256 kbps"
        if self.codec == "aptX": return "~352 kbps"
        if self.codec == "aptX HD": return "~576 kbps"
        if "aptX Adaptive" in self.codec: return "~420 kbps"
        if self.codec == "LDAC": return "~990 kbps"
        return ""


def _is_audio_device(device_class: int) -> bool:
    """Check if a Bluetooth device class indicates audio capability.

    Major service class bit 21 = Audio.
    Device major class 0x04 = Audio/Video.
    """
    AUDIO_SERVICE = 1 << 21
    MAJOR_CLASS_MASK = 0x1F00
    AUDIO_MAJOR = 0x0400
    if device_class & AUDIO_SERVICE:
        return True
    return (device_class & MAJOR_CLASS_MASK) == AUDIO_MAJOR


def _query_system_profiler() -> list[dict]:
    """Parse system_profiler SPBluetoothDataType -json output."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPBluetoothDataType", "-json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        items = data.get("SPBluetoothDataType", [])
        devices = []
        for controller in items:
            for key, val in controller.items():
                if isinstance(val, list):
                    for entry in val:
                        if isinstance(entry, dict):
                            devices.append(entry)
        return devices
    except Exception:
        return []


def _parse_system_profiler_device(entry: dict) -> BluetoothDevice | None:
    """Convert a system_profiler device dict to BluetoothDevice."""
    name = entry.get("device_name", entry.get("name", ""))
    address = entry.get("device_address", entry.get("address", ""))
    connected = entry.get("device_connected", entry.get("connected", False))
    if isinstance(connected, str):
        connected = connected.lower() == "yes"
    paired = entry.get("device_isPaired", entry.get("paired", False))
    if isinstance(paired, str):
        paired = paired.lower() == "yes"

    # Only report audio-capable connected devices
    device_type = entry.get("device_type", "")
    major_class = entry.get("device_majorClass", "")
    minor_class = entry.get("device_minorClass", "")

    # Heuristic: audio devices often have "Headphones", "Headset", "Speaker"
    audio_keywords = {"headphone", "headset", "speaker", "audio", "a2dp", "hands-free"}
    is_audio = any(kw in device_type.lower() for kw in audio_keywords)
    if not is_audio and not any(kw in minor_class.lower() for kw in audio_keywords):
        # Check for common audio-related minor classes
        if "keyboard" in device_type.lower() or "mouse" in device_type.lower() or "trackpad" in device_type.lower():
            return None

    dev = BluetoothDevice(
        name=name,
        address=address,
        connected=connected,
        paired=paired,
        icon="audio-headphones" if "head" in device_type.lower() else "audio-card",
        channels="Stereo",
    )

    # Battery level (macOS 10.15+ reports this)
    battery = entry.get("device_batteryLevelMain", None)
    if battery is not None:
        try:
            dev.battery = int(str(battery).rstrip("%"))
        except (ValueError, TypeError):
            pass

    return dev


def get_bluetooth_devices() -> list[BluetoothDevice]:
    """Return connected Bluetooth audio devices."""
    devices = []

    # Try pyobjc first (richer data)
    if _HAS_OBJC:
        try:
            paired = IOBluetooth.IOBluetoothDevice.pairedDevices()
            for bt_dev in paired:
                if not bt_dev.isConnected():
                    continue
                device_class = bt_dev.getClassOfDevice()
                if not _is_audio_device(device_class):
                    continue
                name = str(bt_dev.getName() or bt_dev.getDeviceName() or "Unknown")
                addr = str(bt_dev.getAddressString() or "")
                battery = None
                try:
                    b = bt_dev.rawRSSI()
                except Exception:
                    pass
                dev = BluetoothDevice(
                    name=name,
                    address=addr,
                    connected=True,
                    paired=bt_dev.isPaired(),
                    icon="audio-headphones",
                    channels="Stereo",
                    device_class=device_class,
                )
                devices.append(dev)
            if devices:
                return devices
        except Exception:
            pass

    # Fallback: system_profiler
    for entry in _query_system_profiler():
        dev = _parse_system_profiler_device(entry)
        if dev is not None and dev.connected:
            devices.append(dev)

    return devices


def get_host_codecs() -> list[str]:
    """Detect which Bluetooth audio codecs are available on this Mac.

    macOS natively supports SBC and AAC.  aptX and LDAC require
    third-party extensions (e.g. ToothFairy, macOS Sequoia+).
    """
    codecs = ["SBC", "AAC"]  # Always available on macOS

    # Check for aptX support (macOS Ventura 13.2+ has it natively for some chips)
    # We can't easily detect this without the IOBluetooth codec API,
    # so report the commonly available set.
    try:
        ver = platform.mac_ver()[0]
        if ver:
            major_minor = tuple(int(x) for x in ver.split(".")[:2])
            if major_minor >= (15, 0):  # Sequoia+
                codecs.extend(["aptX", "aptX HD", "AAC-ELD"])
    except Exception:
        pass

    return sorted(set(codecs))


def get_device_codecs(address: str) -> list[str]:
    """Get codecs supported by a specific device.

    On macOS, codec negotiation is handled by the Bluetooth stack.
    We return the host codecs as a superset; the actual negotiated
    codec is not directly exposed to applications.
    """
    return get_host_codecs()


def get_active_codec(address: str = "") -> str:
    """Try to determine the currently active A2DP codec.

    On macOS 12+ this can sometimes be read from the Bluetooth defaults.
    Falls back to AAC as the most common default.
    """
    try:
        result = subprocess.run(
            ["defaults", "read", "com.apple.Bluetooth", "AppleA2DPActiveCodec"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            val = result.stdout.strip()
            codec_map = {"0": "SBC", "2": "AAC", "255": "Vendor"}
            return codec_map.get(val, f"Codec#{val}")
    except Exception:
        pass
    return "AAC"  # macOS default for most BT audio devices
