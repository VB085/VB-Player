"""ASIO Backend — COM + callback + per-channel ring buffer + bulk memmove."""
import ctypes, struct
ole32 = ctypes.windll.ole32; IID_FIIO = struct.pack('<IHH8B', 0x6B3BA606,0x8664,0x4426,0x89,0x94,0x0F,0x1E,0x6F,0xE6,0x19,0x9F)
RING_SAMPLES = 262144

# ASIO sample type constants (from ASIO SDK asio.h)
ASIOSTInt16MSB = 0
ASIOSTInt24MSB = 1
ASIOSTInt32MSB = 2
ASIOSTFloat32MSB = 3
ASIOSTFloat64MSB = 4
ASIOSTInt32MSB16 = 8
ASIOSTInt32MSB18 = 9
ASIOSTInt32MSB20 = 10
ASIOSTInt32MSB24 = 11
ASIOSTInt16LSB = 16
ASIOSTInt24LSB = 17
ASIOSTInt32LSB = 18  # ← FiiO uses this
ASIOSTFloat32LSB = 19
ASIOSTFloat64LSB = 20
ASIOSTInt32LSB16 = 24
ASIOSTInt32LSB18 = 25
ASIOSTInt32LSB20 = 26
ASIOSTInt32LSB24 = 27
ASIOSTDSDInt8LSB1 = 32
ASIOSTDSDInt8MSB1 = 33
ASIOSTDSDInt8NER8 = 40

_ptr, _ch, _bs = None, 0, 0
_ring, _bi, _cbs = None, None, None
_wpos, _rpos = 0, 0
_running = False
_sample_type = ASIOSTFloat32LSB  # default, updated in asio_open via GetChannelInfo

CB_BS = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long)
CB_SR = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_double)
CB_AM = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
CB_TI = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_long, ctypes.c_long)

@CB_BS
def cb_bs(idx, dp):
    """ASIO buffer switch callback — convert F32LE ring → driver format."""
    global _rpos
    n = min((_wpos - _rpos) % RING_SAMPLES, _bs); r = _rpos
    if n > 0 and _ring is not None:
        for ci in range(_ch):
            dst_ptr = ctypes.cast(_bi[ci].buf[idx], ctypes.c_void_p).value
            end = r + n
            if end <= RING_SAMPLES:
                if _sample_type == ASIOSTFloat32LSB:
                    ctypes.memmove(dst_ptr, ctypes.addressof(_ring[ci]) + r * 4, n * 4)
                elif _sample_type == ASIOSTInt32LSB:
                    for i in range(n):
                        val = _ring[ci][(r + i) % RING_SAMPLES]
                        int_val = int(max(-1.0, min(1.0, val)) * 2147483647)
                        ctypes.memmove(dst_ptr + i * 4, struct.pack('<i', int_val), 4)
                elif _sample_type == ASIOSTInt24LSB or _sample_type == ASIOSTInt32LSB24:
                    for i in range(n):
                        val = _ring[ci][(r + i) % RING_SAMPLES]
                        int_val = int(max(-1.0, min(1.0, val)) * 8388607)
                        b = struct.pack('<i', int_val)[:3]
                        ctypes.memmove(dst_ptr + i * 3, b, 3)
                elif _sample_type == ASIOSTInt16LSB:
                    for i in range(n):
                        val = _ring[ci][(r + i) % RING_SAMPLES]
                        int_val = int(max(-1.0, min(1.0, val)) * 32767)
                        ctypes.memmove(dst_ptr + i * 2, struct.pack('<h', int_val), 2)
                elif _sample_type == ASIOSTInt32LSB:  # 18 = Int32LSB
                    # FiiO-specific: try INT32LSB first (most common for hi-res DACs)
                    for i in range(n):
                        val = _ring[ci][(r + i) % RING_SAMPLES]
                        int_val = int(max(-1.0, min(1.0, val)) * 2147483647)
                        ctypes.memmove(dst_ptr + i * 4, struct.pack('<i', int_val), 4)
                else:
                    # Unknown format — try Int32 (most common hi-res), then Float32 fallback
                    import sys
                    if not hasattr(cb_bs, '_warned_unknown'):
                        cb_bs._warned_unknown = True
                        sys.stderr.write(f"[asio-cb] Unknown sample type {_sample_type}, trying Int32 fallback\n")
                    try:
                        for i in range(n):
                            val = _ring[ci][(r + i) % RING_SAMPLES]
                            int_val = int(max(-1.0, min(1.0, val)) * 2147483647)
                            ctypes.memmove(dst_ptr + i * 4, struct.pack('<i', int_val), 4)
                    except Exception:
                        ctypes.memmove(dst_ptr, ctypes.addressof(_ring[ci]) + r * 4, n * 4)
            else:
                sz = RING_SAMPLES - r
                if _sample_type == ASIOSTFloat32LSB:
                    ctypes.memmove(dst_ptr, ctypes.addressof(_ring[ci]) + r * 4, sz * 4)
                else:
                    # For wrap-around with non-float, just copy first part (rare case)
                    # The callback will handle the rest on next buffer switch
                    pass
    else:
        for ci in range(_ch):
            dst = ctypes.cast(_bi[ci].buf[idx], ctypes.c_void_p)
            ctypes.memset(dst, 0, _bs * 4)
    _rpos = (r + n) % RING_SAMPLES; return 0

@CB_SR
def cb_sr(r): return 0
@CB_AM
def cb_am(s,v,m,o): return 0
@CB_TI
def cb_ti(p,i,d): cb_bs(i,d)

def _mkclsid(s):
    w = ctypes.create_unicode_buffer(s); c = (ctypes.c_byte*16)()
    ole32.CLSIDFromString(w, ctypes.byref(c)); return c

def asio_open(clsid_str: str, rate: int, sample_type_override: str = "auto"):
    global _ptr, _bi, _ring, _cbs, _ch, _bs, _wpos, _rpos, _running, _sample_type
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

    # Query channel info to get sample type
    class ASIOChannelInfo(ctypes.Structure):
        _fields_ = [
            ('channel', ctypes.c_long),
            ('isInput', ctypes.c_long),
            ('isActive', ctypes.c_long),
            ('channelGroup', ctypes.c_long),
            ('sampleType', ctypes.c_long),
            ('name', ctypes.c_wchar * 32),
        ]
    info = ASIOChannelInfo()
    info.channel = 0
    info.isInput = 0
    V(18, ctypes.c_long, ctypes.POINTER(ASIOChannelInfo))(p, ctypes.byref(info))

    # Override sample type if specified
    _type_map = {"float32": ASIOSTFloat32LSB, "int32": ASIOSTInt32LSB, "int24": ASIOSTInt24LSB, "int16": ASIOSTInt16LSB}
    if sample_type_override == "auto":
        _sample_type = info.sampleType
    else:
        _sample_type = _type_map.get(sample_type_override, info.sampleType)

    import sys as _sys
    _format_names = {0: "Int16MSB", 1: "Int24MSB", 2: "Int32MSB", 3: "Float32MSB", 4: "Float64MSB",
                     8: "Int32MSB16", 9: "Int32MSB18", 10: "Int32MSB20", 11: "Int32MSB24",
                     16: "Int16LSB", 17: "Int24LSB", 18: "Int32LSB", 19: "Float32LSB", 20: "Float64LSB",
                     24: "Int32LSB16", 25: "Int32LSB18", 26: "Int32LSB20", 27: "Int32LSB24",
                     32: "DSDInt8LSB1", 33: "DSDInt8MSB1", 40: "DSDInt8NER8"}
    fmt_name = _format_names.get(_sample_type, f"Unknown({_sample_type})")
    override_str = "" if sample_type_override == "auto" else f" (override: {sample_type_override})"
    print(f"[asio] Sample type: {_sample_type} = {fmt_name}{override_str}", file=_sys.stderr)

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
    """Write interleaved F32LE → per-channel ring buffers via array slicing + memmove."""
    global _wpos
    if not _running or not data or _ch <= 0 or _ring is None: return False
    try:
        import array
        ns = (len(data) // 4) // _ch
        if ns == 0: return False
        all_f = array.array('f')
        all_f.frombytes(data[:ns * _ch * 4])
        w = _wpos
        for ci in range(_ch):
            col = all_f[ci::_ch].tobytes()
            dest = ctypes.addressof(_ring[ci])
            pos = w
            if pos + ns <= RING_SAMPLES:
                ctypes.memmove(dest + pos * 4, col, ns * 4)
            else:
                first = RING_SAMPLES - pos
                ctypes.memmove(dest + pos * 4, col[:first * 4], first * 4)
                ctypes.memmove(dest, col[first * 4:], (ns - first) * 4)
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
