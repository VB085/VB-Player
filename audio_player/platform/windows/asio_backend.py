"""ASIO Backend — COM + callback + per-channel ring buffer + bulk memmove."""
import ctypes, struct
ole32 = ctypes.windll.ole32; IID_FIIO = struct.pack('<IHH8B', 0x6B3BA606,0x8664,0x4426,0x89,0x94,0x0F,0x1E,0x6F,0xE6,0x19,0x9F)
RING_SAMPLES = 262144  # frames per channel

_ptr, _ch, _bs = None, 0, 0
_ring, _bi, _cbs = None, None, None
_wpos, _rpos = 0, 0
_running = False

CB_BS = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long)
CB_SR = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_double)
CB_AM = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
CB_TI = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_long, ctypes.c_long)

@CB_BS
def cb_bs(idx, dp):
    """Bulk memmove from per-channel ring buffers to ASIO output — no Python loops."""
    global _rpos
    n = min((_wpos - _rpos) % RING_SAMPLES, _bs)
    r = _rpos
    if n > 0 and _ring is not None:
        for ci in range(_ch):
            dst = ctypes.cast(_bi[ci].buf[idx], ctypes.POINTER(ctypes.c_float))
            end = r + n
            if end <= RING_SAMPLES:
                ctypes.memmove(dst, ctypes.addressof(_ring[ci]) + r * 4, n * 4)
            else:
                sz = RING_SAMPLES - r
                ctypes.memmove(dst, ctypes.addressof(_ring[ci]) + r * 4, sz * 4)
                ctypes.memmove(
                    ctypes.c_void_p(ctypes.cast(dst, ctypes.c_void_p).value + sz * 4),
                    _ring[ci], (n - sz) * 4)
    else:
        for ci in range(_ch):
            dst = ctypes.cast(_bi[ci].buf[idx], ctypes.POINTER(ctypes.c_float))
            ctypes.memset(ctypes.cast(dst, ctypes.c_void_p), 0, _bs * 4)
    _rpos = (r + n) % RING_SAMPLES
    return 0

@CB_SR
def cb_sr(r): return 0
@CB_AM
def cb_am(s,v,m,o): return 0
@CB_TI
def cb_ti(p,i,d): cb_bs(i,d)

def _mkclsid(s):
    w = ctypes.create_unicode_buffer(s); c = (ctypes.c_byte*16)()
    ole32.CLSIDFromString(w, ctypes.byref(c)); return c

def asio_open(clsid_str: str, rate: int):
    global _ptr, _bi, _ring, _cbs, _ch, _bs, _wpos, _rpos, _running
    ole32.CoInitializeEx(None, 2)
    c = _mkclsid(clsid_str); p = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(c), None, 1, (ctypes.c_char*16)(*IID_FIIO), ctypes.byref(p))
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
    _ring = [(ctypes.c_float * RING_SAMPLES)() for _ in range(_ch)]
    _wpos = _rpos = 0
    cb_bs._dump_buf = bytearray()

    class BI(ctypes.Structure): _fields_ = [('i',ctypes.c_long),('n',ctypes.c_long),('buf',ctypes.c_void_p*2)]
    _bi = (BI * _ch)(); _bi_ref = _bi
    for i in range(_ch): _bi[i].i = 0; _bi[i].n = i

    class CB(ctypes.Structure): _fields_ = [('bs',ctypes.c_void_p),('sr',ctypes.c_void_p),('am',ctypes.c_void_p),('ti',ctypes.c_void_p)]
    _cbs = CB(); _cbs.bs=ctypes.cast(cb_bs,ctypes.c_void_p); _cbs.sr=ctypes.cast(cb_sr,ctypes.c_void_p); _cbs.am=ctypes.cast(cb_am,ctypes.c_void_p); _cbs.ti=ctypes.cast(cb_ti,ctypes.c_void_p)

    if V(19,ctypes.c_long,ctypes.c_void_p,ctypes.c_long,ctypes.c_long,ctypes.c_void_p)(p,ctypes.byref(_bi),_ch,_bs,ctypes.byref(_cbs)):
        asio_close(); return None
    V(7,ctypes.c_long)(p); _running = True
    return (_ch, _bs)

def asio_write(data: bytes):
    """Write interleaved F32LE PCM to per-channel ring buffers.

    Uses numpy for fast vectorized de-interleave + memmove — no Python
    loops, no per-element ctypes writes.
    """
    global _wpos
    if not _running or not data or _ch <= 0 or _ring is None:
        return False

    ns = (len(data) // 4) // _ch
    if ns == 0:
        return False

    try:
        import numpy as np
        arr = np.frombuffer(data[:ns * _ch * 4], dtype=np.float32).reshape(-1, _ch)
        w = _wpos
        for ci in range(_ch):
            col = np.ascontiguousarray(arr[:, ci])
            dest = ctypes.addressof(_ring[ci])
            pos = w
            if pos + ns <= RING_SAMPLES:
                ctypes.memmove(dest + pos * 4, col.ctypes.data_as(ctypes.c_void_p), ns * 4)
            else:
                first = RING_SAMPLES - pos
                ctypes.memmove(dest + pos * 4, col[:first].ctypes.data_as(ctypes.c_void_p), first * 4)
                ctypes.memmove(dest, col[first:].ctypes.data_as(ctypes.c_void_p), (ns - first) * 4)
        _wpos = (w + ns) % RING_SAMPLES
        return True
    except Exception:
        return False

def asio_close():
    global _ptr, _running, _bi, _ring, _cbs
    if not _ptr: return
    vt = ctypes.cast(_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    V = lambda i,r,*a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value)
    if _running: V(8,ctypes.c_long)(_ptr); V(20,ctypes.c_long)(_ptr); _running = False
    V(2,ctypes.c_ulong)(_ptr); _ptr = None; _bi = None; _ring = None; _cbs = None

def asio_set_rate(clsid_str: str, rate: int):
    c = _mkclsid(clsid_str); p = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(c),None,1,(ctypes.c_char*16)(*IID_FIIO),ctypes.byref(p))
    if hr or not p: return
    vt = ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0]
    V = lambda i,r,*a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value)
    V(3,ctypes.c_long,ctypes.c_void_p)(p,None); V(14,ctypes.c_long,ctypes.c_double)(p,float(rate))
    V(2,ctypes.c_ulong)(p)
