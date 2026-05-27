import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from audio_player.player.engine_base import _BaseAudioEngine


def enumerate_hw_devices() -> list[dict]:
    """Enumerate audio output devices via GStreamer DeviceMonitor (CoreAudio)."""
    devices = []
    try:
        mon = Gst.DeviceMonitor()
        caps = Gst.Caps.from_string('audio/x-raw')
        mon.add_filter('Audio/Sink', caps)
        mon.start()

        for i, d in enumerate(mon.get_devices()):
            props = d.get_properties()
            api = props.get_string('device.api') or ''
            raw_id = props.get_value('device.id')
            if raw_id is None:
                continue
            # GstDeviceMonitor returns device.id as a GValue(int); unwrap to
            # a plain Python int so callers can pass it directly to osxaudiosink.
            try:
                device_id = int(raw_id)
            except (ValueError, TypeError):
                device_id = str(raw_id)
            name = props.get_string('device.description') or d.get_display_name()

            devices.append({
                'card': i,
                'device': 0,
                'hw': str(device_id),
                'name': name or f'Device {i}',
                'driver': 'CoreAudio',
                'api': api,
            })

        mon.stop()
    except Exception:
        pass

    return devices if devices else [{
        'card': 0, 'device': 0, 'hw': '',
        'name': 'System Default (CoreAudio)', 'driver': 'CoreAudio',
    }]


class AudioEngine(_BaseAudioEngine):
    """macOS CoreAudio engine."""

    def _default_exclusive_device(self) -> str:
        return ""

    def _create_sink(self) -> Gst.Element:
        if self._exclusive_mode:
            sink = Gst.ElementFactory.make("osxaudiosink", None)
            if sink is None:
                raise RuntimeError("osxaudiosink not available — install GStreamer macOS plugins")
            sink.set_property("latency-time", 5000)   # 5ms (microseconds)
            sink.set_property("buffer-time", 20000)    # 20ms (microseconds)
            hw = self._exclusive_device
            if hw:
                try:
                    sink.set_property("device", int(hw))
                except (ValueError, TypeError):
                    sink.set_property("device", hw)
        else:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
            if sink is None:
                raise RuntimeError("autoaudiosink not available")
        return sink

    def _output_info_dict(self) -> dict:
        if self._exclusive_mode:
            return {
                "name": self._exclusive_device or "CoreAudio Exclusive",
                "driver": "CoreAudio (Exclusive)",
                "mode": "Exclusive Mode",
                "is_exclusive": True,
                "api": "coreaudio",
                "latency": "buffer=20ms, latency≈5ms",
            }
        return {
            "name": "System Default",
            "driver": "CoreAudio (Shared)",
            "mode": "Shared Mode",
            "is_exclusive": False,
            "api": "coreaudio",
            "latency": "System audio mixer",
        }
