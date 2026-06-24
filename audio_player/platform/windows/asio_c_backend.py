"""Thin Python wrapper around asio_ext C extension — mirrors asio_backend API."""
import asio_ext

RING_SAMPLES = asio_ext.ring_frames  # constant from C extension

# Module-level properties (backed by asio_ext)
_ch = 0
_bs = 0
_wpos = 0
_rpos = 0
_ring = True  # non-None sentinel for asio_write checks
_running = False

def asio_open(clsid_str: str, rate: int):
    """Open ASIO device via C extension."""
    global _ch, _bs, _wpos, _rpos, _running
    result = asio_ext.open(clsid_str, rate)
    if result is None:
        return None
    _ch = asio_ext.ch
    _bs = asio_ext.bs
    _wpos = 0
    _rpos = 0
    _running = True
    return result

def asio_write(data: bytes):
    """Write interleaved F32LE PCM via C extension. Returns True/False."""
    global _wpos
    if not _running:
        return False
    ok = asio_ext.write(data)
    if ok:
        # Estimate wpos: each write adds ns frames
        ns = (len(data) // 4) // _ch
        _wpos = (_wpos + ns) % RING_SAMPLES
        # Sync rpos from C extension (used frames)
        used = asio_ext.used()
        _rpos = (_wpos - used) % RING_SAMPLES
    return ok

def asio_close():
    """Close ASIO device via C extension."""
    global _running, _ch, _bs, _wpos, _rpos
    asio_ext.close()
    _running = False
    _ch = _bs = 0
    _wpos = _rpos = 0

def asio_set_rate(clsid_str: str, rate: int):
    """Set sample rate (not implemented in C extension)."""
    pass
