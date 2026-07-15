"""ASIO Worker Process — receives PCM via stdin, plays via ASIO.

Run as: python asio_worker.py <clsid> <rate>
Reads F32LE interleaved PCM from stdin, writes to ASIO until stdin EOF.
Completely isolated from Qt/GIL — pure Python + ctypes ASIO.
"""
import sys, ctypes, struct, array, time

# ── Copy of asio_backend (self-contained, no imports from project) ────
ole32 = ctypes.windll.ole32
RING_SAMPLES = 262144

_ptr, _ch, _bs = None, 0, 0
_drv_clsid = None  # set in asio_open — used as both COM class ID and IID
_ring, _bi, _cbs = None, None, None
_wpos, _rpos = 0, 0
_running = False
wpos_cell = [0]  # initialized in asio_open
rpos_cell = [0]

# CB types (used inside asio_open for closures)
_CB_BS = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long)
_CB_SR = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_double)
_CB_AM = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
_CB_TI = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_long, ctypes.c_long)

def _mkclsid(s):
    w = ctypes.create_unicode_buffer(s); c = (ctypes.c_byte*16)()
    ole32.CLSIDFromString(w, ctypes.byref(c)); return c

def asio_open(clsid_str, rate):
    global _ptr, _bi, _ring, _cbs, _ch, _bs, _wpos, _rpos, _running, _drv_clsid
    ole32.CoInitializeEx(None, 2)
    c = _mkclsid(clsid_str); _drv_clsid = c
    p = ctypes.c_void_p()
    # ASIO: driver CLSID is also the COM interface IID — use same GUID for both
    hr = ole32.CoCreateInstance(ctypes.byref(c), None, 1, ctypes.byref(c), ctypes.byref(p))
    if hr or not p: return None
    _ptr = p; vt = ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0]
    V = lambda i,r,*a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value)
    if V(3, ctypes.c_long, ctypes.c_void_p)(p, None) != 1: asio_close(); return None
    if V(14, ctypes.c_long, ctypes.c_double)(p, float(rate)): asio_close(); return None
    ic,oc = ctypes.c_long(),ctypes.c_long(); V(9,ctypes.c_long,ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_long))(p,ctypes.byref(ic),ctypes.byref(oc))
    _ch = max(oc.value, 2)
    mn,mx,pf,gr = ctypes.c_long(),ctypes.c_long(),ctypes.c_long(),ctypes.c_long()
    V(11,ctypes.c_long,ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_long))(p,ctypes.byref(mn),ctypes.byref(mx),ctypes.byref(pf),ctypes.byref(gr))
    _bs = pf.value or mx.value or 1024
    # Per-channel ring buffers for memmove-based callback (zero Python loop)
    _ring = [array.array('f', [0.0]) * RING_SAMPLES for _ in range(_ch)]
    _ring_addrs = [r.buffer_info()[0] for r in _ring]
    _wpos = _rpos = 0

    class BI(ctypes.Structure): _fields_ = [('i',ctypes.c_long),('n',ctypes.c_long),('buf',ctypes.c_void_p*2)]
    _bi = (BI * _ch)(); _bi_ref = _bi
    for i in range(_ch): _bi[i].i = 0; _bi[i].n = i

    class CB(ctypes.Structure): _fields_ = [('bs',ctypes.c_void_p),('sr',ctypes.c_void_p),('am',ctypes.c_void_p),('ti',ctypes.c_void_p)]

    # Callbacks — memmove from per-channel rings to ASIO buffers (zero Python loop)
    ring_ref = _ring
    ring_addrs = _ring_addrs
    bi_ref = _bi
    bs_ref = _bs
    ch_ref = _ch
    wpos_cell[0] = _wpos
    rpos_cell[0] = _rpos

    @_CB_BS
    def _cb_bs(idx, dp):
        w = wpos_cell[0]
        r = rpos_cell[0]
        n = min((w - r) % RING_SAMPLES, bs_ref)
        if n > 0 and ring_ref is not None:
            for ci in range(ch_ref):
                dst_ptr = ctypes.cast(bi_ref[ci].buf[idx], ctypes.c_void_p).value
                end = r + n
                if end <= RING_SAMPLES:
                    ctypes.memmove(dst_ptr, ring_addrs[ci] + r * 4, n * 4)
                else:
                    sz = RING_SAMPLES - r
                    ctypes.memmove(dst_ptr, ring_addrs[ci] + r * 4, sz * 4)
                    ctypes.memmove(dst_ptr + sz * 4, ring_addrs[ci], (n - sz) * 4)
        else:
            for ci in range(ch_ref):
                dst = ctypes.cast(bi_ref[ci].buf[idx], ctypes.c_void_p)
                ctypes.memset(dst, 0, bs_ref * 4)
        rpos_cell[0] = (r + n) % RING_SAMPLES
        return 0

    @_CB_SR
    def _cb_sr(r): return 0
    @_CB_AM
    def _cb_am(s,v,m,o): return 0
    @_CB_TI
    def _cb_ti(p,i,d): _cb_bs(i,d)

    _cbs = CB()
    _cbs.bs = ctypes.cast(_cb_bs, ctypes.c_void_p)
    _cbs.sr = ctypes.cast(_cb_sr, ctypes.c_void_p)
    _cbs.am = ctypes.cast(_cb_am, ctypes.c_void_p)
    _cbs.ti = ctypes.cast(_cb_ti, ctypes.c_void_p)

    if V(19,ctypes.c_long,ctypes.c_void_p,ctypes.c_long,ctypes.c_long,ctypes.c_void_p)(p,ctypes.byref(_bi),_ch,_bs,ctypes.byref(_cbs)):
        asio_close(); return None
    V(7,ctypes.c_long)(p); _running = True
    return (_ch, _bs)

def asio_write(data):
    """Write interleaved float32 data to per-channel ring buffers.

    Deinterleaves using memoryview stride slicing + tobytes() — C-level
    contiguous copy, ~0.03ms for 8K samples (60x faster than Python loop).
    Then memmove into each channel's ring buffer.
    """
    if not _running or not data or _ch <= 0 or _ring is None:
        return False
    frame_bytes = _ch * 4
    ns = len(data) // frame_bytes
    if ns == 0:
        return False

    src_mv = memoryview(data[:ns * frame_bytes]).cast('f')
    w = wpos_cell[0]
    for ci in range(_ch):
        ch_bytes = src_mv[ci::_ch].tobytes()
        ring_addr = _ring_addrs[ci]
        end = w + ns
        if end <= RING_SAMPLES:
            ctypes.memmove(ring_addr + w * 4, ch_bytes, ns * 4)
        else:
            sz = RING_SAMPLES - w
            ctypes.memmove(ring_addr + w * 4, ch_bytes[:sz * 4], sz * 4)
            ctypes.memmove(ring_addr, ch_bytes[sz * 4:], (ns - sz) * 4)

    wpos_cell[0] = (w + ns) % RING_SAMPLES
    return True

def asio_close():
    global _ptr, _running, _bi, _ring, _cbs
    if not _ptr: return
    vt = ctypes.cast(_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    V = lambda i,r,*a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value)
    if _running: V(8,ctypes.c_long)(_ptr); V(20,ctypes.c_long)(_ptr); _running = False
    V(2,ctypes.c_ulong)(_ptr); _ptr = None; _bi = None; _ring = None; _cbs = None

# ── Main: read PCM from stdin, play via ASIO ──────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: asio_worker.py <clsid> <rate>", file=sys.stderr)
        sys.exit(1)

    clsid = sys.argv[1]
    rate = int(sys.argv[2])

    result = asio_open(clsid, rate)
    if result is None:
        print(f"ASIO open failed: {clsid} @ {rate}", file=sys.stderr)
        sys.exit(1)

    ch, bs = result
    print(f"ASIO ready: {ch}ch, {bs}buf, {rate}Hz", file=sys.stderr, flush=True)

    # Raise Windows timer resolution to 1ms — default is ~15.6ms which
    # exceeds the ASIO callback interval (bs/rate ≈ 11.6ms), causing
    # buffer starvation and crackling during time.sleep().
    _WINMM = ctypes.windll.winmm
    _WINMM.timeBeginPeriod(1)

    chunk_size = bs * ch * 4
    eof = False
    try:
        while _running:
            used = (wpos_cell[0] - rpos_cell[0]) % RING_SAMPLES
            free = RING_SAMPLES - used - bs
            if free > 0 and not eof:
                want = min(free * ch * 4, chunk_size, 16384)
                data = sys.stdin.buffer.read(want)
                if data:
                    asio_write(data)
                else:
                    eof = True
            else:
                time.sleep(0.001)
            if eof and wpos_cell[0] == rpos_cell[0]:
                time.sleep(0.3)
                break
    except KeyboardInterrupt:
        pass
    finally:
        asio_close()
