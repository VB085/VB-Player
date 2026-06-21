"""Bluetooth audio device info via BlueZ D-Bus."""

import subprocess
import re
from dataclasses import dataclass
from typing import Optional


CODEC_NAMES = {
    0: "SBC", 1: "MPEG-1/2", 2: "AAC", 3: "ATRAC", 255: "Vendor",
}
SBC_FREQ_MAP = {16: 16000, 32: 32000, 64: 44100, 128: 48000}
SBC_BLOCK_MAP = {4: 4, 8: 8, 16: 12, 32: 16}


@dataclass
class BluetoothDevice:
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
    state: str = ""
    volume: int = 0
    battery: Optional[int] = None

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


def _introspect(path: str) -> str:
    """Run busctl introspect and return output."""
    result = subprocess.run(
        ["busctl", "introspect", "org.bluez", path],
        capture_output=True, text=True, timeout=3
    )
    return result.stdout if result.returncode == 0 else ""


def _parse_property(text: str, name: str, pattern: str) -> Optional[str]:
    """Extract a property value from introspect output."""
    m = re.search(rf'\.{name}\s+property\s+{pattern}', text)
    return m.group(1) if m else None


def _parse_caps(caps_str: str) -> bytes:
    """Parse busctl 'ay N x y z' format — skip the array length prefix."""
    parts = [int(x) for x in caps_str.split()]
    if not parts:
        return b""
    # First part is always the D-Bus array length; skip it
    return bytes(parts[1:]) if len(parts) > 1 else b""


def _get_managed_paths() -> list[str]:
    """Get all object paths from BlueZ via GetManagedObjects."""
    result = subprocess.run(
        ["busctl", "call", "org.bluez", "/",
         "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        return []
    # Extract unique paths — paths are between quotes and start with /org/bluez
    return sorted(set(re.findall(r'"(/org/bluez/hci\d+/dev_[^"]+)"', result.stdout)))


def get_bluetooth_devices() -> list[BluetoothDevice]:
    """Query BlueZ for connected Bluetooth audio devices."""
    devices = []
    all_paths = _get_managed_paths()

    # Get unique device paths (without /sep suffix)
    dev_paths = sorted(set(
        p for p in all_paths
        if "/sep" not in p and "/fd" not in p
    ))

    for dev_path in dev_paths:
        dev_out = _introspect(dev_path)
        if not dev_out:
            continue

        connected = _parse_property(dev_out, "Connected", r'b\s+(true|false)')
        if connected != "true":
            continue

        name = _parse_property(dev_out, "Name", r's\s+"([^"]*)"') or \
               _parse_property(dev_out, "Alias", r's\s+"([^"]*)"') or "Unknown"
        icon = _parse_property(dev_out, "Icon", r's\s+"([^"]*)"') or "audio-card"
        paired = _parse_property(dev_out, "Paired", r'b\s+(true|false)') == "true"

        dev = BluetoothDevice(name=name, icon=icon, paired=paired)
        # Extract address from path: /org/bluez/hci0/dev_XX_XX_XX_XX_XX_XX
        addr_match = re.search(r'/dev_([A-F0-9_]+)$', dev_path)
        if addr_match:
            dev.address = addr_match.group(1).replace("_", ":")
            dev.connected = True

        # Find transport path for this device
        tp_paths = [p for p in all_paths
                    if p.startswith(dev_path + "/sep") and "/fd" in p]
        if tp_paths:
            tp_out = _introspect(tp_paths[0])
            if tp_out:
                codec_str = _parse_property(tp_out, "Codec", r'y\s+(\d+)')
                if codec_str:
                    dev.codec_id = int(codec_str)

                dev.state = _parse_property(tp_out, "State", r's\s+"([^"]*)"') or ""
                vol_str = _parse_property(tp_out, "Volume", r'q\s+(-?\d+)')
                if vol_str:
                    dev.volume = int(vol_str)

                config_str = _parse_property(tp_out, "Configuration",
                                             r'ay\s+(\d+(?: \d+)*)')
                if config_str:
                    caps = bytes(int(x) for x in config_str.split())
                    if caps and caps[0] == len(caps) - 1:
                        caps = caps[1:]
                    _apply_config(caps, dev)

        # Set codec name from active codec_id
        if not dev.codec:
            dev.codec = CODEC_NAMES.get(dev.codec_id, f"#{dev.codec_id}")

        # Check endpoints for SBC XQ capability
        if dev.codec_id == 0:
            ep_paths = sorted(p for p in all_paths
                              if p.startswith(dev_path + "/sep") and "/fd" not in p)
            for ep_path in ep_paths:
                ep_out = _introspect(ep_path)
                if not ep_out:
                    continue
                cid_str = _parse_property(ep_out, "Codec", r'y\s+(\d+)')
                caps_str = _parse_property(ep_out, "Capabilities", r'ay\s+(\d+(?: \d+)*)')
                if cid_str and int(cid_str) == 0 and caps_str:
                    caps = _parse_caps(caps_str)
                    if len(caps) >= 4 and caps[3] >= 53:
                        dev.codec = "SBC XQ"
                        dev.bitpool_max = 53
                    break

        devices.append(dev)

    return devices


def _apply_config(caps: bytes, dev: BluetoothDevice):
    """Apply codec configuration from capabilities/config bytes."""
    if dev.codec_id == 0 and len(caps) >= 4:
        # caps may be endpoint Capabilities (bitmasks) or transport Configuration (values)
        # Check if first byte looks like a bitmask (> 4 bits set) or a value (0-3)
        if caps[0] > 4 or caps[0] == 0:
            # Endpoint capabilities [freq_bitmask, block_bitmask, subband_alloc, bitpool_max]
            dev.bitpool_max = caps[3] if len(caps) > 3 else 53
            for b, n in sorted(SBC_FREQ_MAP.items(), reverse=True):
                if caps[0] & b:
                    dev.frequency = f"{n/1000:.0f} kHz"
                    break
            dev.channels = "Stereo"
            if caps[3] >= 53:
                dev.codec = "SBC XQ"
        else:
            # Transport configuration: [freq_val, block_val, subband_val, alloc_val, min_bp, max_bp]
            FREQ_VALS = {0: "16 kHz", 1: "32 kHz", 2: "44.1 kHz", 3: "48 kHz"}
            BLOCK_VALS = {0: "Mono", 1: "Dual", 2: "Stereo", 3: "Joint Stereo"}
            dev.frequency = FREQ_VALS.get(caps[0], "")
            dev.channels = BLOCK_VALS.get(caps[1], "Stereo")
            if len(caps) > 4:
                dev.bitpool_max = caps[4]
    elif dev.codec_id == 2:  # AAC
        dev.channels = "Stereo"
    elif dev.codec_id == 255 and len(caps) >= 2:
        vid = caps[1] << 8 | caps[0]
        if vid == 0x00D7:
            dev.codec = "aptX Adaptive"
        elif vid == 0x012D:
            dev.codec = "LDAC"
        else:
            dev.codec = f"Vendor(0x{vid:04X})"
        dev.channels = "Stereo"


def get_host_codecs() -> list[str]:
    """Detect which Bluetooth codecs are available on this system."""
    codecs = ["SBC", "SBC XQ"]
    # Check installed codec libraries
    try:
        result = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=3)
        libs = result.stdout
        if "libfdk-aac" in libs:
            codecs.append("AAC")
        if "libopenaptx" in libs:
            codecs.extend(["aptX", "aptX HD"])
        if "libldac" in libs.lower():
            codecs.append("LDAC")
    except Exception:
        pass
    return codecs


def get_device_codecs(address: str) -> list[str]:
    """Get all codecs supported by a specific device."""
    all_paths = _get_managed_paths()
    addr_u = address.replace(":", "_")
    dev_prefix = f"/org/bluez/hci0/dev_{addr_u}"

    codecs = []
    ep_paths = sorted(p for p in all_paths
                      if p.startswith(dev_prefix + "/sep") and "/fd" not in p)
    for ep_path in ep_paths:
        ep_out = _introspect(ep_path)
        if not ep_out:
            continue
        cid_str = _parse_property(ep_out, "Codec", r'y\s+(\d+)')
        caps_str = _parse_property(ep_out, "Capabilities", r'ay\s+(\d+(?: \d+)*)')
        if not cid_str:
            continue
        cid = int(cid_str)
        if cid == 0:
            codecs.append("SBC")
            if caps_str:
                caps = _parse_caps(caps_str)
                if len(caps) >= 4 and caps[3] >= 53:
                    codecs.append("SBC XQ")
        elif cid == 255:
            if caps_str:
                caps = _parse_caps(caps_str)
                if len(caps) >= 2:
                    vid = caps[1] << 8 | caps[0]
                    if vid == 0x00D7: codecs.append("aptX Adaptive")
                    elif vid == 0x012D: codecs.append("LDAC")
                    else: codecs.append(f"Vendor(0x{vid:04X})")
            else:
                codecs.append("Vendor")
        else:
            codecs.append(CODEC_NAMES.get(cid, f"#{cid}"))
    return sorted(set(codecs))
