import sys

from audio_player.player._types import PlaybackState  # noqa: F401

try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst  # noqa: F401 — ensure GStreamer is available
    _HAS_GST = True
except (ImportError, ValueError):
    _HAS_GST = False

if _HAS_GST and sys.platform == 'win32':
    from audio_player.player.engine_windows import AudioEngine, enumerate_hw_devices  # noqa: F401
elif _HAS_GST and sys.platform == 'darwin':
    from audio_player.player.engine_macos import AudioEngine, enumerate_hw_devices  # noqa: F401
elif _HAS_GST:
    from audio_player.player.engine_linux import AudioEngine, enumerate_hw_devices  # noqa: F401
else:
    class AudioEngine:  # type: ignore
        """Stub when GStreamer is not installed."""
        def __init__(self, *a, **kw):
            raise RuntimeError("GStreamer is required but not installed")
    def enumerate_hw_devices():
        return []
