import sys

from audio_player.player._types import PlaybackState  # noqa: F401

# MSVC Python: use ffmpeg + sounddevice engine (no GStreamer needed)
# MSYS2/MinGW Python: use GStreamer engine
_IS_MSVC = hasattr(sys, 'getwindowsversion') and 'MSC' in sys.version
if sys.platform == 'win32' and _IS_MSVC:
    import sys as _s; _s.stderr.write("[engine] using MSVC ffmpeg engine\n")
    from audio_player.player.engine_mswin import MSAudioEngine as AudioEngine  # noqa: F401

    def enumerate_hw_devices():
        """Enumerate WASAPI (via sounddevice) + ASIO (via asio_ctypes/registry)."""
        import sounddevice as _sd
        devices = []

        # ── WASAPI devices ──
        try:
            host_apis = _sd.query_hostapis()
            wasapi_idx = None
            for i, api in enumerate(host_apis):
                if 'wasapi' in api['name'].lower():
                    wasapi_idx = i
                    break
            if wasapi_idx is not None:
                for d in _sd.query_devices():
                    if d['hostapi'] == wasapi_idx and d['max_output_channels'] > 0:
                        name = d.get('name', 'Unknown')
                        if 'microphone' in name.lower():
                            continue
                        devices.append({
                            "card": len(devices),
                            "device": 0,
                            "hw": str(d.get('index', '')),
                            "name": name,
                            "driver": "WASAPI",
                            "api": "wasapi",
                        })
        except Exception:
            pass

        # ── ASIO devices from registry ──
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ASIO")
            i = 0
            while True:
                try:
                    key_name = winreg.EnumKey(key, i)
                    sub = winreg.OpenKey(key, key_name)
                    clsid = winreg.QueryValueEx(sub, "CLSID")[0]
                    driver_name = winreg.QueryValueEx(sub, "Description")[0]
                    devices.append({
                        "card": len(devices),
                        "device": 0,
                        "hw": f"asio:{clsid}",
                        "name": driver_name,
                        "driver": "ASIO",
                        "api": "asio",
                    })
                    winreg.CloseKey(sub)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

        if not devices:
            return [{"card": 0, "device": 0, "hw": "",
                     "name": "Default", "driver": "WASAPI"}]
        return devices
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
