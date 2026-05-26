import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from audio_player.player.engine_base import _BaseAudioEngine


def enumerate_hw_devices() -> list[dict]:
    """Return list of WASAPI audio devices. Stub — returns default device only."""
    return [{"card": 0, "device": 0, "hw": "",
             "name": "默认设备 (WASAPI Shared)"}]


class AudioEngine(_BaseAudioEngine):
    """Windows WASAPI2 audio engine."""

    def _default_exclusive_device(self) -> str:
        return ""

    def _create_sink(self) -> Gst.Element:
        if self._exclusive_mode:
            sink = Gst.ElementFactory.make("wasapi2sink", None)
            if sink is None:
                raise RuntimeError("wasapi2sink 不可用 — 请安装 GStreamer WASAPI 插件")
            sink.set_property("exclusive", True)
            sink.set_property("low-latency", True)
            if self._exclusive_device:
                sink.set_property("device", self._exclusive_device)
        else:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
            if sink is None:
                raise RuntimeError("autoaudiosink 不可用")
        return sink

    def _output_info_dict(self) -> dict:
        if self._exclusive_mode:
            return {
                "name": self._exclusive_device or "WASAPI 默认设备",
                "driver": "WASAPI (独占模式)",
                "mode": "独占模式 (Exclusive)",
            }
        return {
            "name": "系统默认",
            "driver": "WASAPI Shared",
            "mode": "共享模式 (Shared)",
        }
