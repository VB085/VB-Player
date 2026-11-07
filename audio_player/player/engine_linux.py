import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from audio_player.player.engine_base import _BaseAudioEngine
from audio_player.platform.linux.alsa_hw import enumerate_alsa_playback_devices
from audio_player.i18n import _


def enumerate_hw_devices() -> list[dict]:
    """Return ALSA playback devices with card + PCM names (e.g. HDMI 1)."""
    return enumerate_alsa_playback_devices()


class AudioEngine(_BaseAudioEngine):
    """Linux ALSA audio engine."""

    def _default_exclusive_device(self) -> str:
        """Pick a real playback device instead of the often-invalid hw:0,0.

        Prefer analog / USB outputs over HDMI, and skip the "Deep Buffer"
        pseudo-device so bit-perfect does not jump to a display output.
        """
        devices = enumerate_alsa_playback_devices()
        for dev in devices:
            pcm = (dev.get("pcm_name") or "").lower()
            if "hdmi" not in pcm and "deep buffer" not in pcm:
                return dev["hw"]
        return devices[0]["hw"] if devices else "hw:0,0"

    def _create_sink(self) -> Gst.Element:
        if self._exclusive_mode:
            sink = Gst.ElementFactory.make("alsasink", None)
            if sink is None:
                raise RuntimeError(_("engine.alsa_unavailable"))
            sink.set_property("device", self._exclusive_device)
        else:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
            if sink is None:
                raise RuntimeError(_("engine.auto_unavailable"))
        return sink

    def _output_info_dict(self) -> dict:
        if self._exclusive_mode:
            return {
                "name": self._exclusive_device,
                "driver": _("engine.alsa_driver"),
                "mode": _("engine.exclusive_mode"),
                "is_exclusive": True,
                "api": "alsa",
                "latency": _("engine.alsa_buffer"),
            }
        return {
            "name": _("output.system_default"),
            "driver": "PipeWire / PulseAudio",
            "mode": _("engine.shared_mode"),
            "is_exclusive": False,
            "api": "pulse",
            "latency": _("engine.sound_server"),
        }
