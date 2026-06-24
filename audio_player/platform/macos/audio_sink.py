"""CoreAudio HAL device enumeration via ctypes.

Provides device UID, transport type (USB / AirPlay / Bluetooth),
channel count, sample rate, and default-device getter/setter.
All calls use the C AudioToolbox framework through ctypes -- no pyobjc
dependency for this module.
"""

import ctypes
import ctypes.util
import sys
from dataclasses import dataclass, field
from typing import Optional

_HAS_DARWIN = sys.platform == "darwin"

# ---------------------------------------------------------------------------
# Load AudioToolbox framework
# ---------------------------------------------------------------------------

_lib = None
if _HAS_DARWIN:
    try:
        _lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("AudioToolbox"))
    except (OSError, TypeError):
        pass

# ---------------------------------------------------------------------------
# CoreAudio constants
# ---------------------------------------------------------------------------

kAudioHardwarePropertyDefaultOutputDevice = b"dOut"
kAudioHardwarePropertyDevices = b"dev#"
kAudioDevicePropertyDeviceUID = b"uid "
kAudioDevicePropertyDeviceNameCFString = b"name"
kAudioDevicePropertyTransportType = b"tran"
kAudioDevicePropertyStreamConfiguration = b"scnc"
kAudioDevicePropertyNominalSampleRate = b"nsrt"
kAudioObjectPropertyScopeOutput = b"outp"
kAudioObjectPropertyElementMain = 0

# Transport type constants
kAudioDeviceTransportTypeBuiltIn  = 0x6275696C  # 'buil'
kAudioDeviceTransportTypeUSB      = 0x75736220  # 'usb '
kAudioDeviceTransportTypeAirPlay  = 0x61697270  # 'airp'
kAudioDeviceTransportTypeBluetooth      = 0x626C6574  # 'blet'
kAudioDeviceTransportTypeBluetoothLE    = 0x626C6531  # 'ble1'
kAudioDeviceTransportTypeHDMI     = 0x68646D69  # 'hdmi'

_TRANSPORT_NAMES = {
    kAudioDeviceTransportTypeBuiltIn: "Built-in",
    kAudioDeviceTransportTypeUSB: "USB",
    kAudioDeviceTransportTypeAirPlay: "AirPlay",
    kAudioDeviceTransportTypeBluetooth: "Bluetooth",
    kAudioDeviceTransportTypeBluetoothLE: "Bluetooth LE",
    kAudioDeviceTransportTypeHDMI: "HDMI",
}

# ---------------------------------------------------------------------------
# ctypes helper types
# ---------------------------------------------------------------------------

OSStatus = ctypes.c_int32
AudioObjectID = ctypes.c_uint32
AudioClassID = ctypes.c_uint32
AudioObjectPropertyAddress = ctypes.c_char * 4  # actually 12 bytes = 3 x uint32


def _make_address(selector: bytes, scope: bytes = b"glob",
                  element: int = 0) -> bytes:
    """Build an AudioObjectPropertyAddress (12 bytes packed)."""
    import struct
    return struct.pack("4sI I", selector,
                       {b"glob": 0, b"outp": 1, b"inpt": 2}.get(scope, 0),
                       element)


# ---------------------------------------------------------------------------
# C function wrappers (lazy -- only called on macOS)
# ---------------------------------------------------------------------------

def _check(status: int, label: str = ""):
    if status != 0:
        raise OSError(f"CoreAudio error {status} in {label}")


def _get_property_data(obj_id: int, address: bytes,
                       data_size: int) -> tuple[int, bytes]:
    """AudioObjectGetPropertyData -- returns (actual_size, raw_bytes)."""
    if _lib is None:
        return 0, b""
    actual = ctypes.c_uint32(0)
    buf = ctypes.create_string_buffer(data_size)
    addr = (ctypes.c_uint8 * 12).from_buffer_copy(address)
    status = _lib.AudioObjectGetPropertyData(
        ctypes.c_uint32(obj_id),
        ctypes.byref(addr),
        ctypes.c_uint32(0), None,
        ctypes.byref(actual),
        buf,
    )
    if status != 0:
        return 0, b""
    return actual.value, buf.raw[:actual.value]


def _set_property_data(obj_id: int, address: bytes, data: bytes) -> bool:
    """AudioObjectSetPropertyData -- returns True on success."""
    if _lib is None:
        return False
    addr = (ctypes.c_uint8 * 12).from_buffer_copy(address)
    status = _lib.AudioObjectSetPropertyData(
        ctypes.c_uint32(obj_id),
        ctypes.byref(addr),
        ctypes.c_uint32(0), None,
        ctypes.c_uint32(len(data)),
        data,
    )
    return status == 0


def _get_audio_object_ids() -> list[int]:
    """Return all audio object IDs."""
    import struct
    addr = _make_address(kAudioHardwarePropertyDevices)
    # First query size
    actual, _ = _get_property_data(1, addr, 4)
    if actual == 0:
        return []
    count = actual // 4
    actual2, raw = _get_property_data(1, addr, actual)
    if actual2 == 0:
        return []
    return [struct.unpack_from("I", raw, i * 4)[0] for i in range(count)]


def _get_device_uid(device_id: int) -> str:
    """Get the CFString UID of a device."""
    addr = _make_address(kAudioDevicePropertyDeviceUID)
    # CFStringRef is a pointer (8 bytes on 64-bit)
    _, raw = _get_property_data(device_id, addr, 8)
    if len(raw) < 8:
        return ""
    cf_ref = ctypes.c_void_p(ctypes.c_uint64.from_buffer_copy(raw).value)
    if not cf_ref.value:
        return ""
    # Convert CFString to C string via CFStringGetCString
    try:
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        buf = ctypes.create_string_buffer(256)
        ok = cf.CFStringGetCString(cf_ref, buf, 256, 0x08000100)  # kCFStringEncodingUTF8
        return buf.value.decode("utf-8", errors="replace") if ok else ""
    except Exception:
        return ""


def _get_device_name(device_id: int) -> str:
    """Get the human-readable name of a device."""
    addr = _make_address(kAudioDevicePropertyDeviceNameCFString)
    _, raw = _get_property_data(device_id, addr, 8)
    if len(raw) < 8:
        return ""
    cf_ref = ctypes.c_void_p(ctypes.c_uint64.from_buffer_copy(raw).value)
    if not cf_ref.value:
        return ""
    try:
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        buf = ctypes.create_string_buffer(256)
        ok = cf.CFStringGetCString(cf_ref, buf, 256, 0x08000100)
        return buf.value.decode("utf-8", errors="replace") if ok else ""
    except Exception:
        return ""


def _get_transport_type(device_id: int) -> int:
    """Get transport type as a 4-char code integer."""
    addr = _make_address(kAudioDevicePropertyTransportType)
    _, raw = _get_property_data(device_id, addr, 4)
    if len(raw) < 4:
        return 0
    import struct
    return struct.unpack("I", raw)[0]


def _get_channel_count(device_id: int) -> int:
    """Get number of output channels."""
    addr = _make_address(kAudioDevicePropertyStreamConfiguration, b"outp")
    # AudioBufferList: first uint32 is mNumberBuffers, then per buffer:
    #   uint32 mNumberChannels, uint32 mDataByteSize, pointer mData
    # For a size query we just need the buffer list size
    actual, raw = _get_property_data(device_id, addr, 4096)
    if actual < 4:
        return 0
    import struct
    n_buffers = struct.unpack_from("I", raw, 0)[0]
    channels = 0
    offset = 4
    for _ in range(n_buffers):
        if offset + 12 > actual:
            break
        ch = struct.unpack_from("I", raw, offset)[0]
        channels += ch
        offset += 12  # skip mNumberChannels + mDataByteSize + pointer
    return channels


def _get_nominal_sample_rate(device_id: int) -> float:
    """Get the current nominal sample rate."""
    addr = _make_address(kAudioDevicePropertyNominalSampleRate)
    _, raw = _get_property_data(device_id, addr, 8)
    if len(raw) < 8:
        return 0.0
    import struct
    return struct.unpack("d", raw)[0]


def _set_nominal_sample_rate(device_id: int, rate: float) -> bool:
    """Set the nominal sample rate. Returns True on success."""
    import struct
    addr = _make_address(kAudioDevicePropertyNominalSampleRate)
    data = struct.pack("d", rate)
    return _set_property_data(device_id, addr, data)


def _get_default_output_device() -> int:
    """Get the default output device ID."""
    addr = _make_address(kAudioHardwarePropertyDefaultOutputDevice)
    _, raw = _get_property_data(1, addr, 4)  # 1 = kAudioObjectSystemObject
    if len(raw) < 4:
        return 0
    import struct
    return struct.unpack("I", raw)[0]


def _set_default_output_device(device_id: int) -> bool:
    """Set the default output device. Returns True on success."""
    import struct
    addr = _make_address(kAudioHardwarePropertyDefaultOutputDevice)
    return _set_property_data(1, addr, struct.pack("I", device_id))


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------

@dataclass
class CoreAudioDevice:
    """Describes a CoreAudio output device."""
    device_id: int = 0
    uid: str = ""
    name: str = ""
    transport: str = ""          # "USB", "AirPlay", "Bluetooth", etc.
    transport_raw: int = 0
    channels: int = 0
    sample_rate: float = 0.0
    is_default: bool = False

    @property
    def transport_display(self) -> str:
        return _TRANSPORT_NAMES.get(self.transport_raw, "Unknown")


# ---------------------------------------------------------------------------
# Public enumeration API
# ---------------------------------------------------------------------------

def enumerate_output_devices() -> list[CoreAudioDevice]:
    """Enumerate all CoreAudio output devices with rich metadata."""
    if _lib is None:
        return []
    devices = []
    default_id = _get_default_output_device()
    for dev_id in _get_audio_object_ids():
        uid = _get_device_uid(dev_id)
        name = _get_device_name(dev_id)
        if not name:
            continue
        transport_raw = _get_transport_type(dev_id)
        channels = _get_channel_count(dev_id)
        rate = _get_nominal_sample_rate(dev_id)
        devices.append(CoreAudioDevice(
            device_id=dev_id,
            uid=uid,
            name=name,
            transport=_TRANSPORT_NAMES.get(transport_raw, "Unknown"),
            transport_raw=transport_raw,
            channels=channels,
            sample_rate=rate,
            is_default=(dev_id == default_id),
        ))
    return devices


def get_default_device() -> CoreAudioDevice | None:
    """Return the current default output device, or None."""
    if _lib is None:
        return None
    dev_id = _get_default_output_device()
    if dev_id == 0:
        return None
    uid = _get_device_uid(dev_id)
    name = _get_device_name(dev_id)
    transport_raw = _get_transport_type(dev_id)
    channels = _get_channel_count(dev_id)
    rate = _get_nominal_sample_rate(dev_id)
    return CoreAudioDevice(
        device_id=dev_id, uid=uid, name=name,
        transport=_TRANSPORT_NAMES.get(transport_raw, "Unknown"),
        transport_raw=transport_raw, channels=channels,
        sample_rate=rate, is_default=True,
    )


def set_default_device(device_id: int) -> bool:
    """Set the system default output device. Returns True on success."""
    return _set_default_output_device(device_id)


def set_sample_rate(device_id: int, rate: float) -> bool:
    """Set a device's nominal sample rate. Returns True on success."""
    return _set_nominal_sample_rate(device_id, rate)


def get_device_info(device_id: int) -> dict:
    """Return a dict with uid, name, transport, channels, sample_rate."""
    return {
        "uid": _get_device_uid(device_id),
        "name": _get_device_name(device_id),
        "transport": _TRANSPORT_NAMES.get(_get_transport_type(device_id), "Unknown"),
        "channels": _get_channel_count(device_id),
        "sample_rate": _get_nominal_sample_rate(device_id),
    }
