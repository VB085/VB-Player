/** ASIO C Extension — ring buffer + callback in C, no Python in audio path. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>

/* vtable indices */
enum { VI_RELEASE=2, VI_INIT=3, VI_START=7, VI_STOP=8,
       VI_GETCH=9, VI_GETBS=11, VI_CANRATE=12, VI_SETRATE=14,
       VI_CRBUF=19, VI_DISPBUF=20 };

#define RING_FRAMES 262144
#define RING_MASK (RING_FRAMES - 1)

typedef long ASErr;

/* Global state */
static void          *g_dev = NULL;      /* ASIO driver COM pointer */
static float         *g_ring = NULL;     /* interleaved ring buffer [L,R,L,R,...] */
static void         **g_bufs = NULL;     /* per-channel ASIO output buffer pointers (double-buffered) */
static long           g_bs = 0;          /* ASIO buffer size in samples */
static long           g_ch = 0;          /* channel count */
static volatile long  g_wpos = 0;        /* write position (frames) */
static volatile long  g_rpos = 0;        /* read position (frames) */
static CRITICAL_SECTION g_lock;          /* protects ring buffer access */

/* Helper: call ASIO vtable function */
static ASErr _call(int idx, ...) {
    void **vt = *(void***)g_dev;
    void *fn = vt[idx];
    /* Minimal: all ASIO calls have similar signatures, cast and pray */
    return ((ASErr(*)(void*,...))fn)(g_dev);
}

/* ASIO buffer info struct */
typedef struct { long isIn; long ch; void *buf[2]; } ASIOBufInfo;

/* ASIO callback: copy from ring buffer to output buffers */
static long __cdecl _bufSwitch(long idx, long dir) {
    (void)dir;
    EnterCriticalSection(&g_lock);
    long w = g_wpos, r = g_rpos;
    long n = (w - r) & RING_MASK;
    if (n > g_bs) n = g_bs;
    long stride = (long)(g_ch * sizeof(float));
    if (n > 0 && g_ring && g_bufs) {
        for (long ci = 0; ci < g_ch; ci++) {
            float *dst = ((float**)g_bufs)[ci * 2 + idx];
            float *src = g_ring + ci; /* start at channel ci */
            long r1 = r;
            if (r1 + n <= RING_FRAMES) {
                for (long i = 0; i < n; i++) {
                    dst[i] = src[(r1 + i) * g_ch];
                }
            } else {
                long sz = RING_FRAMES - r1;
                for (long i = 0; i < sz; i++)
                    dst[i] = src[(r1 + i) * g_ch];
                for (long i = 0; i < n - sz; i++)
                    dst[sz + i] = src[i * g_ch];
            }
        }
        g_rpos = (r + n) & RING_MASK;
    } else if (g_bufs) {
        /* Underrun: output silence */
        long bs = g_bs;
        for (long ci = 0; ci < g_ch; ci++) {
            float *dst = ((float**)g_bufs)[ci * 2 + idx];
            memset(dst, 0, bs * sizeof(float));
        }
    }
    LeaveCriticalSection(&g_lock);
    return 0;
}
static long __cdecl _srChange(double r) { (void)r; return 0; }
static long __cdecl _asioMsg(long s, long v, void *m, double *o) {
    (void)s; (void)v; (void)m; (void)o; return 0;
}
static void __cdecl _timeInfo(void *p, long i, long d) { _bufSwitch(i, d); }

typedef struct { void *bs; void *sr; void *am; void *ti; } ASIOCBs;

/* Python: asio_ext.open(clsid_str, rate) → (channels, buf_size) or None */
static PyObject *ext_open(PyObject *self, PyObject *args) {
    const char *cs; double rate;
    if (!PyArg_ParseTuple(args, "sd", &cs, &rate)) return NULL;
    if (g_dev) { Py_RETURN_NONE; }

    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);

    /* Parse CLSID string → GUID */
    wchar_t w[64] = {0};
    MultiByteToWideChar(CP_UTF8, 0, cs, -1, w, 64);
    CLSID clsid; HRESULT hr = CLSIDFromString(w, &clsid);
    if (FAILED(hr)) { Py_RETURN_NONE; }

    /* Create ASIO driver instance */
    void *dev = NULL;
    /* FiiO workaround: use driver's own CLSID as IID */
    hr = CoCreateInstance(&clsid, NULL, CLSCTX_INPROC_SERVER, &clsid, &dev);
    if (FAILED(hr) || !dev) { Py_RETURN_NONE; }

    ASErr e;
    /* Init */
    e = ((ASErr(*)(void*,void*))(((void**)dev)[VI_INIT]))(dev, NULL);
    if (e != 1) { ((void(*)(void*))(((void**)dev)[VI_RELEASE]))(dev); Py_RETURN_NONE; }
    /* Set sample rate */
    e = ((ASErr(*)(void*,double))(((void**)dev)[VI_SETRATE]))(dev, rate);
    if (e != 0) { ((void(*)(void*))(((void**)dev)[VI_RELEASE]))(dev); Py_RETURN_NONE; }
    /* Get channels */
    long ic = 0, oc = 0;
    ((ASErr(*)(void*,long*,long*))(((void**)dev)[VI_GETCH]))(dev, &ic, &oc);
    if (oc < 2) oc = 2;
    /* Get buffer size */
    long mn = 0, mx = 0, pf = 0, gr = 0;
    ((ASErr(*)(void*,long*,long*,long*,long*))(((void**)dev)[VI_GETBS]))(dev, &mn, &mx, &pf, &gr);
    long bs = pf ? pf : (mx ? mx : 1024);
    if (bs < 64) bs = 1024;

    /* Create buffer infos */
    ASIOBufInfo *bi = calloc(oc, sizeof(ASIOBufInfo));
    for (long i = 0; i < oc; i++) { bi[i].isIn = 0; bi[i].ch = i; }
    /* Setup callbacks */
    ASIOCBs cb = { _bufSwitch, _srChange, _asioMsg, _timeInfo };
    e = ((ASErr(*)(void*,void*,long,long,void*))(((void**)dev)[VI_CRBUF]))(dev, bi, oc, bs, &cb);
    if (e != 0) { free(bi); ((void(*)(void*))(((void**)dev)[VI_RELEASE]))(dev); Py_RETURN_NONE; }

    /* Extract buffer pointers */
    void **bufs = calloc(oc * 2, sizeof(void*));
    for (long i = 0; i < oc; i++) {
        bufs[i * 2 + 0] = bi[i].buf[0];
        bufs[i * 2 + 1] = bi[i].buf[1];
    }
    free(bi);

    /* Create ring buffer */
    float *ring = calloc(RING_FRAMES * oc, sizeof(float));

    /* Start ASIO */
    ((ASErr(*)(void*))(((void**)dev)[VI_START]))(dev);

    /* Initialize globals */
    InitializeCriticalSection(&g_lock);
    g_dev = dev;
    g_ring = ring;
    g_bufs = bufs;
    g_bs = bs;
    g_ch = oc;
    g_wpos = 0;
    g_rpos = 0;

    return Py_BuildValue("ll", oc, bs);
}

/* Python: asio_ext.write(data_bytes) → bool */
static PyObject *ext_write(PyObject *self, PyObject *args) {
    Py_buffer buf;
    if (!PyArg_ParseTuple(args, "y*", &buf)) return NULL;
    if (!g_dev || !g_ring) { PyBuffer_Release(&buf); Py_RETURN_FALSE; }

    long ns = (long)(buf.len / sizeof(float) / g_ch);
    if (ns <= 0) { PyBuffer_Release(&buf); Py_RETURN_FALSE; }

    EnterCriticalSection(&g_lock);
    long w = g_wpos;
    /* Available space */
    long used = (w - g_rpos) & RING_MASK;
    long free = RING_FRAMES - used - 1;
    if (ns > free) ns = free;
    if (ns <= 0) { LeaveCriticalSection(&g_lock); PyBuffer_Release(&buf); Py_RETURN_FALSE; }

    float *src = (float*)buf.buf;
    long nbytes = ns * g_ch * (long)sizeof(float);
    long offset = (w & RING_MASK) * g_ch;
    if (offset + ns * g_ch <= RING_FRAMES * g_ch) {
        memcpy(g_ring + offset, src, nbytes);
    } else {
        long first = RING_FRAMES * g_ch - offset;
        memcpy(g_ring + offset, src, first * sizeof(float));
        memcpy(g_ring, src + first, (ns * g_ch - first) * sizeof(float));
    }
    g_wpos = (w + ns) & RING_MASK;
    LeaveCriticalSection(&g_lock);

    PyBuffer_Release(&buf);
    Py_RETURN_TRUE;
}

/* Python: asio_ext.close() */
static PyObject *ext_close(PyObject *self, PyObject *args) {
    if (!g_dev) Py_RETURN_FALSE;
    ((ASErr(*)(void*))(((void**)g_dev)[VI_STOP]))(g_dev);
    ((ASErr(*)(void*))(((void**)g_dev)[VI_DISPBUF]))(g_dev);
    ((void(*)(void*))(((void**)g_dev)[VI_RELEASE]))(g_dev);
    DeleteCriticalSection(&g_lock);
    free(g_bufs); g_bufs = NULL;
    free(g_ring); g_ring = NULL;
    g_dev = NULL; g_ch = g_bs = 0; g_wpos = g_rpos = 0;
    Py_RETURN_TRUE;
}

/* Python: asio_ext.used() → frames in ring buffer */
static PyObject *ext_used(PyObject *self, PyObject *args) {
    if (!g_dev) return PyLong_FromLong(0);
    long used = (g_wpos - g_rpos) & RING_MASK;
    return PyLong_FromLong(used);
}

/* Python: asio_ext.bs, asio_ext.ch, asio_ext.ring_frames */
static PyObject *ext_get(PyObject *self, void *closure) {
    int id = (int)(intptr_t)closure;
    switch (id) {
        case 0: return PyLong_FromLong(g_bs);
        case 1: return PyLong_FromLong(g_ch);
        case 2: return PyLong_FromLong(RING_FRAMES);
        case 3: return PyBool_FromLong(g_dev != NULL);
    }
    Py_RETURN_NONE;
}

static PyGetSetDef ext_getsets[] = {
    {"bs", ext_get, NULL, NULL, (void*)0},
    {"ch", ext_get, NULL, NULL, (void*)1},
    {"ring_frames", ext_get, NULL, NULL, (void*)2},
    {"running", ext_get, NULL, NULL, (void*)3},
    {NULL}
};

static PyMethodDef methods[] = {
    {"open", ext_open, METH_VARARGS, "Open ASIO device (clsid, rate) → (ch, bs) or None"},
    {"write", ext_write, METH_VARARGS, "Write interleaved F32LE PCM bytes → bool"},
    {"close", ext_close, METH_VARARGS, "Close ASIO device"},
    {"used", ext_used, METH_VARARGS, "Frames buffered in ring buffer"},
    {NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "asio_ext", "ASIO native C backend", -1, methods
};

PyMODINIT_FUNC PyInit_asio_ext(void) {
    return PyModule_Create(&module);
}
