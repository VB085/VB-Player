import sys

from audio_player.player._types import PlaybackState  # noqa: F401

# MSVC Python: use ffmpeg + sounddevice engine (no GStreamer needed)
# MSYS2/MinGW Python: use GStreamer engine
_IS_MSVC = hasattr(sys, 'getwindowsversion') and 'MSC' in sys.version
if sys.platform == 'win32' and _IS_MSVC:
    import sys as _s; _s.stderr.write("[engine] using MSVC ffmpeg engine\n")
    from audio_player.player.engine_mswin import MSAudioEngine as AudioEngine  # noqa: F401
    def enumerate_hw_devices():
        return [{"card": 0, "device": 0, "hw": "", "name": "Default", "driver": "WASAPI"}]
else:
    try:
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst  # noqa: F401
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
        class AudioEngine:
            def __init__(self, *a, **kw):
                raise RuntimeError("GStreamer is required but not installed")
        def enumerate_hw_devices():
            return []
