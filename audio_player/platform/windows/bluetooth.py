"""Windows Bluetooth audio device scanner.

Detects Bluetooth audio render devices via GStreamer DeviceMonitor (WASAPI).
Matches the same BluetoothDevice / get_bluetooth_devices / get_host_codecs /
get_device_codecs API as the Linux BlueZ implementation.
"""

from dataclasses import dataclass
from typing import Optional


# Shared with platform/linux/bluetooth.py — keep in sync
CODEC_NAMES = {
    0: "SBC", 1: "MPEG-1/2", 2: "AAC", 3: "ATRAC", 255: "Vendor",
}


@dataclass
class BluetoothDevice:
    """Bluetooth audio device descriptor. Same fields as Linux version."""
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


def _enumerate_bt_devices() -> list[dict]:
    """Use GStreamer DeviceMonitor to find Bluetooth audio sinks."""
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)

    devices = []
    try:
        mon = Gst.DeviceMonitor()
        caps = Gst.Caps.from_string('audio/x-raw')
        mon.add_filter('Audio/Sink', caps)
        mon.start()

        for d in mon.get_devices():
            props = d.get_properties()
            api = props.get_string('device.api') or ''
            enumerator = props.get_string('device.enumerator-name') or ''

            # Only Bluetooth devices
            if enumerator != 'BTHENUM':
                continue
            # Skip microphone / capture devices
            name = props.get_string('device.description') or d.get_display_name()
            if name and 'microphone' in name.lower():
                continue
            if api == 'asio':
                continue

            device_id = props.get_value('device.id') or ''
            if not device_id:
                continue

            devices.append({
                'name': name or 'Bluetooth Device',
                'hw': device_id,
            })

        mon.stop()
    except Exception:
        pass

    return devices


def _read_bluetooth_registry_property(device_id: str, value_name: str) -> Optional[str]:
    """Try to read a Bluetooth device property from the Windows registry.

    Windows stores paired Bluetooth device info under
    HKLM\\SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices\\
    """
    import winreg
    try:
        # Extract MAC-like pattern from device_id if present
        # WASAPI device IDs look like: {0.0.0.00000000}.{GUID}
        # Bluetooth MAC is sometimes embedded in the GUID portion
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices",
        ) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        name_val, _ = winreg.QueryValueEx(subkey, "Name")
                        if name_val and name_val.lower() == device_id.lower():
                            val, _ = winreg.QueryValueEx(subkey, value_name)
                            return str(val)
                except OSError:
                    continue
    except OSError:
        pass
    return None


def get_bluetooth_devices() -> list[BluetoothDevice]:
    """Return connected Bluetooth audio render devices."""
    bt_data = _enumerate_bt_devices()
    devices = []

    for d in bt_data:
        name = d['name']
        hw = d['hw']

        # Try to extract MAC address from the WASAPI device ID
        # Format: {0.0.0.00000000}.{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
        mac = ""
        import re
        guid_match = re.search(
            r'\{([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
            r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}', hw
        )
        if guid_match:
            # Last 6 bytes of GUID sometimes encode MAC
            guid = guid_match.group(1)
            hex_parts = guid.replace('-', '')
            if len(hex_parts) >= 12:
                # Take last 6 bytes as MAC approximation
                mac_bytes = hex_parts[-12:]
                mac = ':'.join(mac_bytes[i:i+2] for i in range(0, 12, 2)).upper()

        if not mac:
            # Use device ID hash as fallback identifier
            mac = f"BT:{abs(hash(hw)) % (256**3):06X}"
            # Format as MAC-like
            mac = ':'.join(mac[i:i+2] for i in range(0, len(mac), 2))

        dev = BluetoothDevice(
            name=name,
            address=mac,
            icon="audio-card",
            connected=True,
            paired=True,
            codec="SBC",  # Windows default codec — OS manages negotiation
            channels="Stereo",
            state="active",
        )

        # Windows typically uses 44.1kHz or 48kHz for Bluetooth
        # Exact parameters are negotiated by the OS (not exposed to apps)
        dev.frequency = "44.1/48 kHz"

        devices.append(dev)

    return devices


def get_host_codecs() -> list[str]:
    """Return Bluetooth codecs supported by the Windows Bluetooth stack.

    On Windows, the Bluetooth stack (Microsoft or vendor) negotiates
    codecs automatically. This reports commonly available codecs.
    SBC is always available per A2DP spec.
    """
    codecs = ["SBC"]
    import sys
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\BthA2dp\Parameters",
        ) as key:
            # Check if AAC is enabled
            try:
                aac_val, _ = winreg.QueryValueEx(key, "EnableAAC")
                if int(aac_val) != 0:
                    codecs.append("AAC")
            except OSError:
                pass
            try:
                aptx_val, _ = winreg.QueryValueEx(key, "EnableAptX")
                if int(aptx_val) != 0:
                    codecs.extend(["aptX", "aptX HD"])
            except OSError:
                pass
    except OSError:
        # Registry key may not exist — just report SBC
        pass

    # Check for LDAC (third-party drivers)
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Drivers32",
        ) as key:
            for i in range(winreg.QueryInfoKey(key)[1]):
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    if 'ldac' in str(value).lower():
                        codecs.append("LDAC")
                        break
                except OSError:
                    continue
    except OSError:
        pass

    return sorted(set(codecs))


def get_device_codecs(address: str) -> list[str]:
    """Return codecs supported by a specific Bluetooth device.

    On Windows, the OS handles codec negotiation and doesn't expose
    per-device codec capabilities to applications. We return the set
    that is commonly available.
    """
    # Without WinRT, we can't query device-specific codec support.
    # Most A2DP devices support SBC (mandatory) + possibly AAC/aptX.
    codecs = ["SBC"]
    # Add host codecs as a superset — the intersection is handled by
    # the caller (network_page)
    host = get_host_codecs()
    if "AAC" in host:
        codecs.append("AAC")
    if "aptX" in host:
        codecs.extend(["aptX", "aptX HD"])
    return sorted(set(codecs))
