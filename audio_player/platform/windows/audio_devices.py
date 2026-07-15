"""Windows audio device enumeration — mirrors Linux API for network_page."""

import sys
from dataclasses import dataclass
from audio_player.i18n import _

_IS_MSVC = hasattr(sys, 'getwindowsversion') and 'MSC' in sys.version


@dataclass
class AudioDevice:
    id: str = "local"
    name: str = ""
    device_type: str = "local"  # "local", "wired", "bluetooth"
    description: str = ""
    available: bool = True
    active: bool = False
    codec: str = ""
    sample_rate: str = ""
    detail: str = ""
    api: str = ""


def get_local_device(active: bool = False) -> AudioDevice:
    return AudioDevice(
        id="local",
        name=_("engine.default_device"),
        device_type="local",
        description="WASAPI Shared",
        available=True,
        active=active,
    )


def get_wasapi_devices(exclusive_on: bool = False) -> list[AudioDevice]:
    """Enumerate WASAPI + ASIO render devices."""
    if _IS_MSVC:
        return _get_msvc_devices()
    from audio_player.player.engine_windows import enumerate_hw_devices
    devs = []
    for d in enumerate_hw_devices():
        ad = AudioDevice(
            id=f"hw:{d.get('hw', '')}",
            name=d.get("name", ""),
            device_type="wired",
            description=d.get("driver", ""),
            available=True,
            active=False,
            api=d.get("api", ""),
        )
        devs.append(ad)
    return devs


def _get_msvc_devices() -> list[AudioDevice]:
    """Device enumeration for MSVC Python (sounddevice + asio_ctypes)."""
    import sounddevice as sd
    devs = []
    # WASAPI devices via sounddevice
    try:
        host_apis = sd.query_hostapis()
        wasapi_idx = None
        for i, api in enumerate(host_apis):
            if 'wasapi' in api['name'].lower():
                wasapi_idx = i
                break
        if wasapi_idx is not None:
            for d in sd.query_devices():
                if d['hostapi'] == wasapi_idx and d['max_output_channels'] > 0:
                    devs.append(AudioDevice(
                        id=f"wasapi:{d.get('index', d.get('name', ''))}",
                        name=d.get('name', 'Unknown'),
                        device_type="wired",
                        description="WASAPI",
                        available=True,
                        active=False,
                        api="wasapi",
                    ))
    except Exception:
        pass

    # Always add a default entry
    if not devs:
        devs.append(get_local_device(active=False))

    # ASIO devices via asio_ctypes
    try:
        from audio_player.platform.windows import asio_ctypes
        drivers = asio_ctypes.list_drivers()
        for drv in drivers:
            devs.append(AudioDevice(
                id=f"asio:{drv['clsid']}",
                name=drv.get('name', 'ASIO Device'),
                device_type="wired",
                description="ASIO",
                available=True,
                active=False,
                api="asio",
            ))
    except Exception:
        pass

    return devs


def get_wired_devices() -> list[AudioDevice]:
    """Alias for get_wasapi_devices."""
    return get_wasapi_devices()


def get_alsa_hw_devices() -> list[AudioDevice]:
    """Windows alias — returns WASAPI exclusive devices."""
    return get_wasapi_devices(exclusive_on=True)


# ---------------------------------------------------------------------------
# Real-time device monitor
# ---------------------------------------------------------------------------

class DeviceWatcher:
    """Persistent GStreamer DeviceMonitor — fires Qt signals on device changes.

    On MSVC Python (no GStreamer), this is a no-op stub.
    """

    def __init__(self):
        self._monitor = None
        self._callbacks = []

    def start(self):
        if _IS_MSVC:
            return  # No GStreamer DeviceMonitor on MSVC
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst
        Gst.init(None)

        mon = Gst.DeviceMonitor()
        caps = Gst.Caps.from_string('audio/x-raw')
        mon.add_filter('Audio/Sink', caps)
        mon.start()

        def on_added(monitor, device):
            for cb in self._callbacks:
                try:
                    cb('added', device)
                except Exception:
                    pass

        def on_removed(monitor, device):
            for cb in self._callbacks:
                try:
                    cb('removed', device)
                except Exception:
                    pass

        mon.connect('device-added', on_added)
        mon.connect('device-removed', on_removed)
        self._monitor = mon

    def stop(self):
        if self._monitor:
            try:
                self._monitor.stop()
            except Exception:
                pass
            self._monitor = None

    def on_change(self, callback):
        """Register callback(change_type, GstDevice) on device add/remove."""
        self._callbacks.append(callback)
