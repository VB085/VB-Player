"""ASIO Backend — COM + callback + interleaved ring buffer."""
import ctypes, struct, threading as _thr
ole32 = ctypes.windll.ole32; IID_FIIO = struct.pack('<IHH8B', 0x6B3BA606,0x8664,0x4426,0x89,0x94,0x0F,0x1E,0x6F,0xE6,0x19,0x9F)
RING_SAMPLES = 262144  # frames (per channel)

_ptr, _ch, _bs = None, 0, 0
_ring = None  # single interleaved float array: [L0,R0,L1,R1,...]
_ring_i = None  # interleaved bytearray for main-thread writes
_bi, _cbs = None, None
_wpos, _rpos = 0, 0  # in frames
_running = False

CB_BS = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long)
CB_SR = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_double)
CB_AM = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
CB_TI = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_long, ctypes.c_long)

@CB_BS
def cb_bs(idx, dp):
    global _rpos
    n = min((_wpos - _rpos) % RING_SAMPLES, _bs)
    r = _rpos
    bytes_per_frame = _ch * 4
    # Accumulate callback output for diagnostic dump
    _dump_buf = getattr(cb_bs, '_dump_buf', None)
    if _dump_buf is None:
        cb_bs._dump_buf = bytearray()
        _dump_buf = cb_bs._dump_buf
    _dump_target = 256 * 1024  # collect 256KB (~1.5s at 44.1kHz stereo f32)
    if len(_dump_buf) < _dump_target and n > 0 and _ring is not None:
        import array
        out = array.array('f')
        for i in range(n):
            src_off = ((r + i) % RING_SAMPLES) * bytes_per_frame
            for ci in range(_ch):
                ptr = ctypes.cast(ctypes.c_void_p(ctypes.addressof(_ring) + src_off + ci * 4),
                                  ctypes.POINTER(ctypes.c_float))
                out.append(ptr[0])
        _dump_buf.extend(out.tobytes())  # F32LE bytes, same format as asio_dump
        if len(_dump_buf) >= _dump_target:
            # Convert to 16-bit WAV
            import struct as _st, os
            f32_all = array.array('f')
            f32_all.frombytes(bytes(_dump_buf))
            s16 = array.array('h', (int(max(-1., min(1., v)) * 32767) for v in f32_all))
            wav_data = s16.tobytes()
            rate = 44100
            wav = bytearray(44 + len(wav_data))
            wav[0:4] = b'RIFF'; _st.pack_into('<I', wav, 4, 36 + len(wav_data))
            wav[8:16] = b'WAVEfmt '; _st.pack_into('<I', wav, 16, 16)
            _st.pack_into('<H', wav, 20, 1); _st.pack_into('<H', wav, 22, _ch)
            _st.pack_into('<I', wav, 24, rate); _st.pack_into('<I', wav, 28, rate * _ch * 2)
            _st.pack_into('<H', wav, 32, _ch * 2); _st.pack_into('<H', wav, 34, 16)
            wav[36:40] = b'data'; _st.pack_into('<I', wav, 40, len(wav_data))
            wav[44:] = wav_data
            desktop = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
            with open(os.path.join(desktop, 'asio_cb_dump.wav'), 'wb') as f:
                f.write(bytes(wav))
            import sys; sys.stderr.write(f"[cb] dumped {len(_dump_buf)} bytes → Desktop/asio_cb_dump.wav\n")

    if n > 0 and _ring is not None:
        # Read from interleaved ring buffer, write to per-channel ASIO output.
        # Uses ctypes array indexing (like the verified standalone beep test).
        src_floats = ctypes.cast(ctypes.addressof(_ring), ctypes.POINTER(ctypes.c_float))
        for ci in range(_ch):
            dst = ctypes.cast(_bi[ci].buf[idx], ctypes.POINTER(ctypes.c_float))
            for i in range(n):
                src_idx = ((r + i) % RING_SAMPLES) * _ch + ci
                dst[i] = src_floats[src_idx]
    else:
        for ci in range(_ch):
            dst = ctypes.cast(_bi[ci].buf[idx], ctypes.POINTER(ctypes.c_float))
            for i in range(_bs):
                dst[i] = 0.0
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
    # Single interleaved ring buffer: [L0,R0,L1,R1,...] — RING_SAMPLES frames × _ch floats
    _ring = (ctypes.c_float * (RING_SAMPLES * _ch))()
    _wpos = _rpos = 0
    cb_bs._dump_buf = bytearray()  # reset callback dump

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
    """Write interleaved F32LE PCM directly to ring buffer — no de-interleave."""
    global _wpos
    if not _running or not data or _ch <= 0 or _ring is None:
        return False
    try:
        frames = (len(data) // 4) // _ch
        if frames == 0:
            return False
        n_bytes = frames * _ch * 4
        w = _wpos
        byte_offset = (w % RING_SAMPLES) * _ch * 4
        buf_end = byte_offset + n_bytes
        buf_total = RING_SAMPLES * _ch * 4
        if buf_end <= buf_total:
            ctypes.memmove(
                ctypes.c_void_p(ctypes.addressof(_ring) + byte_offset),
                data[:n_bytes], n_bytes)
        else:
            first = buf_total - byte_offset
            ctypes.memmove(
                ctypes.c_void_p(ctypes.addressof(_ring) + byte_offset),
                data[:first], first)
            ctypes.memmove(
                ctypes.addressof(_ring),
                data[first:n_bytes], n_bytes - first)
        _wpos = (w + frames) % RING_SAMPLES
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
