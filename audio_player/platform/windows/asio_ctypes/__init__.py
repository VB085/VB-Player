"""asio-ctypes — Python ctypes bindings for ASIO audio drivers on Windows.

Usage:
    import asio_ctypes

    dev = asio_ctypes.ASIODevice("{CLSID-GUID}", 44100)
    dev.write(interleaved_f32le_bytes)
    dev.close()
"""

import ctypes
import struct
import array as _array_lib
import sys as _sys

__version__ = "0.1.0"

# ── ASIO Sample Type Constants (from ASIO SDK asio.h) ───────────────
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
ASIOSTInt32LSB = 18
ASIOSTFloat32LSB = 19
ASIOSTFloat64LSB = 20
ASIOSTInt32LSB16 = 24
ASIOSTInt32LSB18 = 25
ASIOSTInt32LSB20 = 26
ASIOSTInt32LSB24 = 27
ASIOSTDSDInt8LSB1 = 32
ASIOSTDSDInt8MSB1 = 33
ASIOSTDSDInt8NER8 = 40

_FORMAT_NAMES = {
    0: "Int16MSB", 1: "Int24MSB", 2: "Int32MSB", 3: "Float32MSB", 4: "Float64MSB",
    8: "Int32MSB16", 9: "Int32MSB18", 10: "Int32MSB20", 11: "Int32MSB24",
    16: "Int16LSB", 17: "Int24LSB", 18: "Int32LSB", 19: "Float32LSB", 20: "Float64LSB",
    24: "Int32LSB16", 25: "Int32LSB18", 26: "Int32LSB20", 27: "Int32LSB24",
    32: "DSDInt8LSB1", 33: "DSDInt8MSB1", 40: "DSDInt8NER8",
}

_FORMAT_OVERRIDE_MAP = {
    "float32": ASIOSTFloat32LSB,
    "int32": ASIOSTInt32LSB,
    "int24": ASIOSTInt24LSB,
    "int16": ASIOSTInt16LSB,
}

RING_SAMPLES = 262144  # frames per channel
_ole32 = ctypes.windll.ole32


def _mk_clsid(s: str) -> bytes:
    """Parse CLSID string → 16-byte GUID."""
    w = ctypes.create_unicode_buffer(s)
    c = (ctypes.c_byte * 16)()
    _ole32.CLSIDFromString(w, ctypes.byref(c))
    return c


class ASIODevice:
    """ASIO audio device via COM interface.

    Handles buffer switching callbacks, ring buffer management,
    and sample format conversion.

    Parameters:
        clsid_str: The CLSID GUID string, e.g. "{6B3BA606-...}".
        rate: Sample rate in Hz (44100, 48000, 96000, etc.).
        sample_format: "auto" to query driver, or "float32"/"int32"/"int24"/"int16".
    """

    # ── Callback types (reusable across instances) ──────────────────
    _CB_BS = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long)
    _CB_SR = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_double)
    _CB_AM = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
    _CB_TI = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_long, ctypes.c_long)

    def __init__(self, clsid_str: str, rate: int, sample_format: str = "auto"):
        self._ptr = None
        self._channels = 0
        self._buffer_size = 0
        self._ring = None
        self._bi = None
        self._cbs = None
        self._wpos = 0
        self._rpos = 0
        self._running = False
        self._sample_type = ASIOSTFloat32LSB

        _ole32.CoInitializeEx(None, 2)
        c = _mk_clsid(clsid_str)
        p = ctypes.c_void_p()
        hr = _ole32.CoCreateInstance(ctypes.byref(c), None, 1, ctypes.byref(c), ctypes.byref(p))
        if hr or not p:
            raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08x}")

        self._ptr = p
        vt = ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0]
        V = lambda i, r, *a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(
            ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value
        )

        if V(3, ctypes.c_long, ctypes.c_void_p)(p, None) != 1:
            self.close(); raise RuntimeError("ASIO Init failed")
        if V(14, ctypes.c_long, ctypes.c_double)(p, float(rate)):
            self.close(); raise RuntimeError(f"ASIO SetSampleRate({rate}) failed")

        ic, oc = ctypes.c_long(), ctypes.c_long()
        V(9, ctypes.c_long, ctypes.POINTER(ctypes.c_long), ctypes.POINTER(ctypes.c_long))(
            p, ctypes.byref(ic), ctypes.byref(oc))
        self._channels = max(oc.value, 2)

        mn, mx, pf, gr = ctypes.c_long(), ctypes.c_long(), ctypes.c_long(), ctypes.c_long()
        V(11, ctypes.c_long, ctypes.POINTER(ctypes.c_long), ctypes.POINTER(ctypes.c_long),
          ctypes.POINTER(ctypes.c_long), ctypes.POINTER(ctypes.c_long))(
            p, ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(pf), ctypes.byref(gr))
        self._buffer_size = pf.value or mx.value or 1024

        # Ring buffers: per-channel float arrays
        self._ring = [(ctypes.c_float * RING_SAMPLES)() for _ in range(self._channels)]

        # Query channel info for sample type
        class _ASIOChannelInfo(ctypes.Structure):
            _fields_ = [
                ("channel", ctypes.c_long), ("isInput", ctypes.c_long),
                ("isActive", ctypes.c_long), ("channelGroup", ctypes.c_long),
                ("sampleType", ctypes.c_long), ("name", ctypes.c_wchar * 32),
            ]
        info = _ASIOChannelInfo()
        info.channel = 0; info.isInput = 0
        V(18, ctypes.c_long, ctypes.POINTER(_ASIOChannelInfo))(p, ctypes.byref(info))

        if sample_format == "auto":
            self._sample_type = info.sampleType
        else:
            self._sample_type = _FORMAT_OVERRIDE_MAP.get(sample_format, info.sampleType)

        fmt_name = _FORMAT_NAMES.get(self._sample_type, f"Unknown({self._sample_type})")
        override_str = "" if sample_format == "auto" else f" (override: {sample_format})"
        print(f"[asio-ctypes] Device opened: {self._channels}ch, {self._buffer_size}buf, "
              f"{rate}Hz, sample={self._sample_type}({fmt_name}){override_str}", file=_sys.stderr)

        # Buffer infos
        class _BI(ctypes.Structure):
            _fields_ = [("i", ctypes.c_long), ("n", ctypes.c_long), ("buf", ctypes.c_void_p * 2)]
        self._bi = (_BI * self._channels)()
        for i in range(self._channels):
            self._bi[i].i = 0; self._bi[i].n = i

        # Build callbacks as closures (avoids global-variable issues)
        ring_ref = self._ring
        bi_ref = self._bi
        bs_ref = self._buffer_size
        ch_ref = self._channels
        st_ref = self._sample_type
        rpos_cell = [0]
        self._rpos_cell = rpos_cell  # expose for external read
        wpos_attr = "_wpos"

        @self._CB_BS
        def _cb_bs(idx, dp):
            import sys as _s
            _s.stderr.write(f"[cb] idx={idx}\n"); _s.stderr.flush()
            r = rpos_cell[0]
            w = getattr(self, wpos_attr)
            n = min((w - r) % RING_SAMPLES, bs_ref)
            if n > 0 and ring_ref is not None:
                for ci in range(ch_ref):
                    dst_ptr = ctypes.cast(bi_ref[ci].buf[idx], ctypes.c_void_p).value
                    if (r + n) <= RING_SAMPLES:
                        self._copy_samples(dst_ptr, ci, r, n, st_ref)
                    else:
                        sz = RING_SAMPLES - r
                        self._copy_samples(dst_ptr, ci, r, sz, st_ref)
            else:
                for ci in range(ch_ref):
                    dst = ctypes.cast(bi_ref[ci].buf[idx], ctypes.c_void_p)
                    ctypes.memset(dst, 0, bs_ref * 4)
            rpos_cell[0] = (r + n) % RING_SAMPLES
            return 0

        self._cb_bs = _cb_bs

        @self._CB_SR
        def _cb_sr(r): return 0

        @self._CB_AM
        def _cb_am(s, v, m, o): return 0

        @self._CB_TI
        def _cb_ti(p, i, d): _cb_bs(i, d)

        # Store callbacks struct (must be instance attr to prevent GC)
        class _CB(ctypes.Structure):
            _fields_ = [("bs", ctypes.c_void_p), ("sr", ctypes.c_void_p),
                       ("am", ctypes.c_void_p), ("ti", ctypes.c_void_p)]
        self._cbs = _CB()
        self._cbs.bs = ctypes.cast(_cb_bs, ctypes.c_void_p)
        self._cbs.sr = ctypes.cast(_cb_sr, ctypes.c_void_p)
        self._cbs.am = ctypes.cast(_cb_am, ctypes.c_void_p)
        self._cbs.ti = ctypes.cast(_cb_ti, ctypes.c_void_p)

        if V(19, ctypes.c_long, ctypes.c_void_p, ctypes.c_long, ctypes.c_long,
             ctypes.c_void_p)(p, ctypes.byref(self._bi), self._channels,
                              self._buffer_size, ctypes.byref(self._cbs)):
            self.close(); raise RuntimeError("ASIO CreateBuffers failed")

        V(7, ctypes.c_long)(p)
        self._running = True

    # ── Internal: copy samples with format conversion ───────────────
    def _copy_samples(self, dst_ptr: int, ch: int, offset: int, count: int, sample_type: int):
        """Copy 'count' frames from ring[ch][offset:] to dst_ptr, converting format."""
        ring = self._ring[ch]
        channels = self._channels
        if sample_type == ASIOSTFloat32LSB:
            ctypes.memmove(dst_ptr, ctypes.addressof(ring) + offset * 4, count * 4)
        elif sample_type in (ASIOSTInt32LSB, 18):
            for i in range(count):
                val = ring[(offset + i) % RING_SAMPLES]
                iv = int(max(-1.0, min(1.0, val)) * 2147483647)
                ctypes.memmove(dst_ptr + i * 4, struct.pack("<i", iv), 4)
        elif sample_type in (ASIOSTInt24LSB, ASIOSTInt32LSB24, 10, 27):
            for i in range(count):
                val = ring[(offset + i) % RING_SAMPLES]
                iv = int(max(-1.0, min(1.0, val)) * 8388607)
                b = struct.pack("<i", iv)[:3]
                ctypes.memmove(dst_ptr + i * 3, b, 3)
        elif sample_type in (ASIOSTInt16LSB, 16, 9):
            for i in range(count):
                val = ring[(offset + i) % RING_SAMPLES]
                iv = int(max(-1.0, min(1.0, val)) * 32767)
                ctypes.memmove(dst_ptr + i * 2, struct.pack("<h", iv), 2)
        else:
            # Unknown format — try Int32 fallback
            for i in range(count):
                val = ring[(offset + i) % RING_SAMPLES]
                iv = int(max(-1.0, min(1.0, val)) * 2147483647)
                ctypes.memmove(dst_ptr + i * 4, struct.pack("<i", iv), 4)

    # ── Public API ──────────────────────────────────────────────────

    @property
    def channels(self) -> int:
        """Number of output channels."""
        return self._channels

    @property
    def buffer_size(self) -> int:
        """ASIO buffer size in samples."""
        return self._buffer_size

    @property
    def sample_format(self) -> int:
        """ASIO sample type constant."""
        return self._sample_type

    @property
    def rpos(self) -> int:
        """Callback read position (updated by ASIO driver thread)."""
        return self._rpos_cell[0]

    @property
    def buffered(self) -> int:
        """Frames currently buffered in the ring buffer."""
        return (self._wpos - self.rpos) % RING_SAMPLES

    @property
    def free(self) -> int:
        """Available space in the ring buffer (frames)."""
        return RING_SAMPLES - self.buffered - 1

    def write(self, data: bytes) -> bool:
        """Write interleaved F32LE PCM data to the ring buffer.

        Args:
            data: Raw bytes of interleaved float32 samples (F32LE).

        Returns:
            True if data was written successfully.
        """
        if not self._running or not data or self._channels <= 0 or self._ring is None:
            return False
        try:
            ns = (len(data) // 4) // self._channels
            if ns == 0:
                return False
            all_f = _array_lib.array("f")
            all_f.frombytes(data[: ns * self._channels * 4])
            w = self._wpos
            for ci in range(self._channels):
                col = all_f[ci :: self._channels].tobytes()
                dest = ctypes.addressof(self._ring[ci])
                pos = w
                if pos + ns <= RING_SAMPLES:
                    ctypes.memmove(dest + pos * 4, col, ns * 4)
                else:
                    first = RING_SAMPLES - pos
                    ctypes.memmove(dest + pos * 4, col[: first * 4], first * 4)
                    ctypes.memmove(dest, col[first * 4 :], (ns - first) * 4)
            self._wpos = (w + ns) % RING_SAMPLES
            return True
        except Exception:
            return False

    def close(self):
        """Stop streaming and release the ASIO device."""
        if not self._ptr:
            return
        vt = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.c_void_p))[0]
        V = lambda i, r, *a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(
            ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value
        )
        if self._running:
            V(8, ctypes.c_long)(self._ptr)   # Stop
            V(20, ctypes.c_long)(self._ptr)  # DisposeBuffers
            self._running = False
        V(2, ctypes.c_ulong)(self._ptr)      # Release
        self._ptr = None
        self._bi = None
        self._ring = None
        self._cbs = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def __del__(self):
        self.close()


def set_rate(clsid_str: str, rate: int):
    """Quickly set a new sample rate on an ASIO driver (creates a temporary instance).

    Useful for changing the system clock rate before opening with ASIODevice.
    """
    c = _mk_clsid(clsid_str)
    p = ctypes.c_void_p()
    hr = _ole32.CoCreateInstance(ctypes.byref(c), None, 1, ctypes.byref(c), ctypes.byref(p))
    if hr or not p:
        return
    vt = ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0]
    V = lambda i, r, *a: ctypes.WINFUNCTYPE(r, ctypes.c_void_p, *a)(
        ctypes.cast(ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[i], ctypes.c_void_p).value
    )
    V(3, ctypes.c_long, ctypes.c_void_p)(p, None)
    V(14, ctypes.c_long, ctypes.c_double)(p, float(rate))
    V(2, ctypes.c_ulong)(p)


def list_drivers() -> list[dict]:
    """Enumerate installed ASIO drivers from the Windows registry.

    Returns a list of dicts with 'name', 'clsid', and 'is_64bit' keys.
    """
    drivers = []
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\ASIO")
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
                sub = winreg.OpenKey(key, name)
                try:
                    clsid = winreg.QueryValueEx(sub, "CLSID")[0]
                except Exception:
                    clsid = ""
                try:
                    comment = winreg.QueryValueEx(sub, "Description")[0]
                except Exception:
                    comment = ""
                winreg.CloseKey(sub)

                # Check if 64-bit COM entry exists
                is_64bit = False
                try:
                    ck = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"CLSID\\{clsid}")
                    winreg.CloseKey(ck)
                    is_64bit = True
                except OSError:
                    pass

                drivers.append({
                    "name": comment or name,
                    "driver_name": name,
                    "clsid": clsid,
                    "is_64bit": is_64bit,
                })
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
    except Exception:
        pass
    return drivers


def is_driver_64bit(clsid: str) -> bool:
    """Check if an ASIO driver is 64-bit compatible."""
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"CLSID\\{clsid}")
        return True
    except OSError:
        return False
