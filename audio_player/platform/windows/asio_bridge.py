"""Compatibility bridge: maps the old asio_backend module API to asio-ctypes class API.

The engine_windows module expects module-level functions and globals:
    _a.asio_open(clsid, rate) -> (channels, buf_size) | None
    _a.asio_write(data: bytes) -> bool
    _a.asio_close()
    _a._wpos, _a._rpos, _a._ch, _a._bs, _a._running, _a.RING_SAMPLES
"""
import asio_ctypes

_dev = None  # current ASIODevice instance

# Mirror asio_ctypes constants
RING_SAMPLES = asio_ctypes.RING_SAMPLES

# Module-level state (mapped from _dev)
_wpos = 0
_rpos = 0
_ch = 0
_bs = 0
_running = False


def asio_open(clsid_str: str, rate: int, sample_type_override: str = "auto"):
    """Open ASIO device. Returns (channels, buf_size) or None."""
    global _dev, _ch, _bs, _running, _wpos, _rpos
    asio_close()
    try:
        _dev = asio_ctypes.ASIODevice(clsid_str, rate, sample_type_override)
        _ch = _dev.channels
        _bs = _dev.buffer_size
        _running = True
        _wpos = 0
        _rpos = 0
        return (_ch, _bs)
    except Exception as e:
        import sys
        print(f"[asio-bridge] open failed: {e}", file=sys.stderr)
        return None


def asio_write(data: bytes) -> bool:
    """Write interleaved F32LE PCM to ring buffer."""
    global _dev, _wpos, _rpos, _ch, _bs
    if _dev is None:
        return False
    ok = _dev.write(data)
    if ok:
        # Update module-level position tracking
        _wpos = _dev._wpos
        _rpos = _dev._rpos
        _ch = _dev._channels
        _bs = _dev._buffer_size
    return ok


def asio_close():
    """Close ASIO device."""
    global _dev, _running, _wpos, _rpos
    if _dev is not None:
        _dev.close()
        _dev = None
    _running = False
    _wpos = 0
    _rpos = 0
