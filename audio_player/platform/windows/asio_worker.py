"""ASIO Worker Process — receives PCM via stdin, plays via ASIO.

Run as: python asio_worker.py <clsid> <rate>
Reads F32LE interleaved PCM from stdin, writes to ASIO until stdin EOF.
Completely isolated from Qt/GIL — pure Python + ctypes ASIO.
"""
import sys, ctypes, struct, array, time

# ── Copy of asio_backend (self-contained, no imports from project) ────
ole32 = ctypes.windll.ole32
IID_FIIO = struct.pack('<IHH8B', 0x6B3BA606,0x8664,0x4426,0x89,0x94,0x0F,0x1E,0x6F,0xE6,0x19,0x9F)
RING_SAMPLES = 262144

_ptr, _ch, _bs = None, 0, 0
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

    class BI(ctypes.Structure): _fields_ = [('i',ctypes.c_long),('n',ctypes.c_long),('buf',ctypes.c_void_p*2)]
    _bi = (BI * _ch)(); _bi_ref = _bi
    for i in range(_ch): _bi[i].i = 0; _bi[i].n = i

    class CB(ctypes.Structure): _fields_ = [('bs',ctypes.c_void_p),('sr',ctypes.c_void_p),('am',ctypes.c_void_p),('ti',ctypes.c_void_p)]

    # Callbacks as CLOSURES — capture _ring, _bi, _rpos directly (standalone test pattern)
    ring_ref = _ring
    bi_ref = _bi
    bs_ref = _bs
    ch_ref = _ch
    wpos_cell[0] = _wpos  # reuse module-level cells
    rpos_cell[0] = _rpos

    @_CB_BS
    def _cb_bs(idx, dp):
        w = wpos_cell[0]
        r = rpos_cell[0]
        n = min((w - r) % RING_SAMPLES, bs_ref)
        if n > 0 and ring_ref is not None:
            for ci in range(ch_ref):
                dst = ctypes.cast(bi_ref[ci].buf[idx], ctypes.POINTER(ctypes.c_float))
                end = r + n
                if end <= RING_SAMPLES:
                    ctypes.memmove(dst, ctypes.addressof(ring_ref[ci]) + r * 4, n * 4)
                else:
                    sz = RING_SAMPLES - r
                    ctypes.memmove(dst, ctypes.addressof(ring_ref[ci]) + r * 4, sz * 4)
                    ctypes.memmove(
                        ctypes.c_void_p(ctypes.cast(dst, ctypes.c_void_p).value + sz * 4),
                        ring_ref[ci], (n - sz) * 4)
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

def _write_wav(path, s16_arr, rate, ch):
    import struct as _st
    wav_data = s16_arr.tobytes()
    wav = bytearray(44 + len(wav_data))
    wav[0:4] = b'RIFF'; _st.pack_into('<I', wav, 4, 36 + len(wav_data))
    wav[8:16] = b'WAVEfmt '; _st.pack_into('<I', wav, 16, 16)
    _st.pack_into('<H', wav, 20, 1); _st.pack_into('<H', wav, 22, ch)
    _st.pack_into('<I', wav, 24, rate); _st.pack_into('<I', wav, 28, rate * ch * 2)
    _st.pack_into('<H', wav, 32, ch * 2); _st.pack_into('<H', wav, 34, 16)
    wav[36:40] = b'data'; _st.pack_into('<I', wav, 40, len(wav_data))
    wav[44:] = wav_data
    with open(path, 'wb') as f: f.write(bytes(wav))

def asio_write(data):
    if not _running or not data or _ch <= 0 or _ring is None: return False
    ns = (len(data) // 4) // _ch
    if ns == 0: return False
    src = (ctypes.c_float * (ns * _ch)).from_buffer_copy(data[:ns * _ch * 4])
    w = wpos_cell[0]
    for ci in range(_ch):
        dst = _ring[ci]
        for i in range(ns):
            dst[(w + i) % RING_SAMPLES] = src[i * _ch + ci]
    # DUMP: read back first 1024 frames from ring buffer and save as WAV
    if not hasattr(asio_write, '_dumped'):
        asio_write._dumped = True
        import array, struct as _st, os

        # Dump INPUT data (what ffmpeg sent us)
        frames_in = min(4096, ns)
        s16_in = array.array('h')
        for i in range(frames_in):
            for ci in range(_ch):
                s16_in.append(int(max(-1., min(1., src[i * _ch + ci])) * 32767))
        rate = 44100
        desktop = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
        _write_wav(os.path.join(desktop, 'worker_INPUT.wav'), s16_in, rate, _ch)

        # Dump RING BUFFER data after write
        frames = min(4096, RING_SAMPLES - w)
        s16 = array.array('h')
        for i in range(frames):
            for ci in range(_ch):
                val = _ring[ci][(w + i) % RING_SAMPLES]
                s16.append(int(max(-1., min(1., val)) * 32767))
        _write_wav(os.path.join(desktop, 'worker_RING.wav'), s16, rate, _ch)
        import sys; sys.stderr.write(f"[write-dump] Desktop/worker_INPUT.wav + worker_RING.wav\n")

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

    # Read from stdin, throttle to ring buffer capacity
    chunk_size = bs * ch * 4
    eof = False
    total_written = 0
    dbg_count = 0
    print("Playing...", file=sys.stderr, flush=True)
    try:
        while _running:
            free = RING_SAMPLES - ((_wpos - _rpos) % RING_SAMPLES) - bs * 2
            free = RING_SAMPLES - ((wpos_cell[0] - rpos_cell[0]) % RING_SAMPLES) - bs * 2
            if free > bs and not eof:
                want = min(free * ch * 4, chunk_size * 4)
                data = sys.stdin.buffer.read(want)
                if data:
                    ok = asio_write(data)
                    total_written += len(data)
                    if dbg_count < 5:
                        print(f"  wrote {len(data)}B (ok={ok}), wpos={wpos_cell[0]}, rpos={rpos_cell[0]}, free={free}",
                              file=sys.stderr, flush=True)
                        dbg_count += 1
                else:
                    eof = True
                    print(f"  EOF after {total_written}B", file=sys.stderr, flush=True)
            else:
                time.sleep(0.01)
            if eof and wpos_cell[0] == rpos_cell[0]:
                time.sleep(0.1)
                break
    except KeyboardInterrupt:
        pass
    finally:
        asio_close()
        print("ASIO closed", file=sys.stderr, flush=True)
