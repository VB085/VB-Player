"""Windows audio device enumeration — mirrors Linux API for network_page."""

from dataclasses import dataclass
from audio_player.i18n import _


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
    """Enumerate WASAPI + ASIO render devices via GStreamer."""
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
    """Persistent GStreamer DeviceMonitor — fires Qt signals on device changes."""

    def __init__(self):
        self._monitor = None
        self._callbacks = []

    def start(self):
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
