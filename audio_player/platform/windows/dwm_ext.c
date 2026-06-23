/**
 * DWM Windows Native Extension — compiled with MSYS2 GCC.
 *
 * Build:
 *   gcc -shared -O2 -o dwm_ext.pyd dwm_ext.c \
 *       -Id:/Claude/coder/VB-Player/.venv/include \
 *       -Ld:/Claude/coder/VB-Player/.venv/libs \
 *       -lpython3.14 -ldwmapi -lole32 -luuid
 *
 * Or simpler via setuptools/distutils.
 *
 * Usage from Python:
 *   import dwm_ext
 *   dwm_ext.apply_mica(hwnd)           # → True/False
 *   dwm_ext.apply_acrylic(hwnd)        # → True/False
 *   dwm_ext.apply_dark_titlebar(hwnd)  # → True/False
 *   dwm_ext.set_progress(hwnd, completed, total)
 *   dwm_ext.clear_progress(hwnd)
 *   dwm_ext.apply_rounded(hwnd)        # → True/False
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dwmapi.h>
#include <commctrl.h>
#include <objbase.h>
#include <shobjidl.h>

/* ------------------------------------------------------------------ */
/* ITaskbarList3 — GUIDs are defined in shobjidl.h (MSYS2 headers)      */
/* ------------------------------------------------------------------ */
static ITaskbarList3 *g_pTaskbar = NULL;

/* ------------------------------------------------------------------ */
/* DWM constants                                                        */
/* ------------------------------------------------------------------ */
#ifndef DWMWA_USE_IMMERSIVE_DARK_MODE
#define DWMWA_USE_IMMERSIVE_DARK_MODE 20
#endif
#ifndef DWMWA_SYSTEMBACKDROP_TYPE
#define DWMWA_SYSTEMBACKDROP_TYPE 38
#endif
#ifndef DWMWA_WINDOW_CORNER_PREFERENCE
#define DWMWA_WINDOW_CORNER_PREFERENCE 33
#endif

enum {
    BACKDROP_NONE = 1,
    BACKDROP_MICA = 2,
    BACKDROP_MICA_ALT = 3,
    BACKDROP_ACRYLIC = 4,
};

enum {
    CORNER_DEFAULT = 0,
    CORNER_DONOTROUND = 1,
    CORNER_ROUND = 2,
    CORNER_ROUNDSMALL = 3,
};

/* ================================================================== */
/* WM_NCCALCSIZE interceptor — tell DWM the entire window is client    */
/* area. This is what Chrome/VSCode do for frameless windows.         */
/* Without this, maximize animation can't interpolate correctly.       */
/* ================================================================== */
static LRESULT CALLBACK
SubclassProc(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam,
             UINT_PTR uIdSubclass, DWORD_PTR dwRefData)
{
    (void)uIdSubclass;
    (void)dwRefData;

    if (uMsg == 0x0083 /* WM_NCCALCSIZE */ && wParam == TRUE) {
        /* Tell DWM: no non-client border, entire window is client */
        return 0;
    }

    return DefSubclassProc(hWnd, uMsg, wParam, lParam);
}

/* ================================================================== */
/* enable_dwm_frame(hwnd) → bool                                        */
/* Makes a frameless Qt window behave like a normal Win32 window:      */
/* 1. Adds WS_OVERLAPPEDWINDOW for DWM animations + taskbar support    */
/* 2. Installs subclass to handle WM_NCCALCSIZE (no native borders)    */
/* 3. Extends DWM frame into client area to hide the caption visually  */
/* ================================================================== */
static PyObject *
dwm_enable_frame(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    if (!PyArg_ParseTuple(args, "K", &hwnd))
        return NULL;

    HWND h = (HWND)hwnd;

    /* Add full standard window styles for DWM animations */
    LONG style = GetWindowLongW(h, GWL_STYLE);
    style |= WS_OVERLAPPEDWINDOW;
    SetWindowLongW(h, GWL_STYLE, style);

    /* Explicitly enable DWM transitions */
    BOOL enable_transitions = FALSE;
    DwmSetWindowAttribute(h, 26 /* DWMWA_TRANSITIONS_FORCEDISABLED */,
                          &enable_transitions, sizeof(enable_transitions));

    /* Install window subclass to tell DWM there's no non-client area */
    SetWindowSubclass(h, SubclassProc, 1, 0);

    /* Extend DWM frame to cover entire client area */
    MARGINS margins = {0, 0, 0, 1};
    DwmExtendFrameIntoClientArea(h, &margins);

    /* Force full frame recalculation */
    SetWindowPos(h, NULL, 0, 0, 0, 0,
                 SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);

    Py_RETURN_TRUE;
}

/* ================================================================== */
/* apply_mica(hwnd) → bool                                             */
/* ================================================================== */
static PyObject *
dwm_apply_mica(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    if (!PyArg_ParseTuple(args, "K", &hwnd))
        return NULL;

    /* Try Win11 22H2+ API first */
    int backdrop = BACKDROP_MICA;
    HRESULT hr = DwmSetWindowAttribute((HWND)hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                                        &backdrop, sizeof(backdrop));
    if (FAILED(hr)) {
        /* Fallback: Win11 21H2 */
        BOOL enable = TRUE;
        hr = DwmSetWindowAttribute((HWND)hwnd, 1029, /* DWMWA_MICA */
                                    &enable, sizeof(enable));
    }

    if (SUCCEEDED(hr)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

/* ================================================================== */
/* apply_acrylic(hwnd) → bool                                           */
/* ================================================================== */
static PyObject *
dwm_apply_acrylic(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    if (!PyArg_ParseTuple(args, "K", &hwnd))
        return NULL;

    int backdrop = BACKDROP_ACRYLIC;
    HRESULT hr = DwmSetWindowAttribute((HWND)hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                                        &backdrop, sizeof(backdrop));
    if (FAILED(hr)) {
        /* Pre-22H2: fallback to Mica */
        BOOL enable = TRUE;
        hr = DwmSetWindowAttribute((HWND)hwnd, 1029, &enable, sizeof(enable));
    }

    if (SUCCEEDED(hr)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

/* ================================================================== */
/* clear_backdrop(hwnd) → bool                                          */
/* ================================================================== */
static PyObject *
dwm_clear_backdrop(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    if (!PyArg_ParseTuple(args, "K", &hwnd))
        return NULL;

    int backdrop = BACKDROP_NONE;
    HRESULT hr = DwmSetWindowAttribute((HWND)hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                                        &backdrop, sizeof(backdrop));
    if (FAILED(hr)) {
        BOOL enable = FALSE;
        hr = DwmSetWindowAttribute((HWND)hwnd, 1029, &enable, sizeof(enable));
    }

    if (SUCCEEDED(hr)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

/* ================================================================== */
/* apply_dark_titlebar(hwnd) → bool                                     */
/* ================================================================== */
static PyObject *
dwm_apply_dark_titlebar(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    int dark;
    if (!PyArg_ParseTuple(args, "Kp", &hwnd, &dark))
        return NULL;

    BOOL value = dark ? TRUE : FALSE;
    HRESULT hr = DwmSetWindowAttribute((HWND)hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                        &value, sizeof(value));
    if (SUCCEEDED(hr)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

/* ================================================================== */
/* apply_rounded_corners(hwnd) → bool                                   */
/* ================================================================== */
static PyObject *
dwm_apply_rounded(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    if (!PyArg_ParseTuple(args, "K", &hwnd))
        return NULL;

    int corner = CORNER_ROUND;
    HRESULT hr = DwmSetWindowAttribute((HWND)hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                        &corner, sizeof(corner));
    if (SUCCEEDED(hr)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

/* ================================================================== */
/* Taskbar progress bar helpers                                         */
/* ================================================================== */

static ITaskbarList3 *
_get_taskbar(void)
{
    if (g_pTaskbar)
        return g_pTaskbar;

    HRESULT hr = CoCreateInstance(&CLSID_TaskbarList, NULL, CLSCTX_INPROC_SERVER,
                                   &IID_ITaskbarList3, (void **)&g_pTaskbar);
    if (FAILED(hr))
        return NULL;

    g_pTaskbar->lpVtbl->HrInit(g_pTaskbar);
    return g_pTaskbar;
}

static PyObject *
dwm_set_progress(PyObject *self, PyObject *args)
{
    unsigned long long hwnd, completed, total;
    if (!PyArg_ParseTuple(args, "KKK", &hwnd, &completed, &total))
        return NULL;

    ITaskbarList3 *ptb = _get_taskbar();
    if (!ptb) Py_RETURN_FALSE;

    if (total > 0) {
        ptb->lpVtbl->SetProgressValue(ptb, (HWND)hwnd, completed, total);
        ptb->lpVtbl->SetProgressState(ptb, (HWND)hwnd, 2); /* TBPF_NORMAL */
    } else {
        ptb->lpVtbl->SetProgressState(ptb, (HWND)hwnd, 0); /* TBPF_NOPROGRESS */
    }

    Py_RETURN_TRUE;
}

static PyObject *
dwm_clear_progress(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    if (!PyArg_ParseTuple(args, "K", &hwnd))
        return NULL;

    ITaskbarList3 *ptb = _get_taskbar();
    if (!ptb) Py_RETURN_FALSE;

    ptb->lpVtbl->SetProgressState(ptb, (HWND)hwnd, 0); /* TBPF_NOPROGRESS */
    Py_RETURN_TRUE;
}

static PyObject *
dwm_set_progress_state(PyObject *self, PyObject *args)
{
    unsigned long long hwnd;
    int state;
    if (!PyArg_ParseTuple(args, "Ki", &hwnd, &state))
        return NULL;

    ITaskbarList3 *ptb = _get_taskbar();
    if (!ptb) Py_RETURN_FALSE;

    ptb->lpVtbl->SetProgressState(ptb, (HWND)hwnd, state);
    Py_RETURN_TRUE;
}

/* ================================================================== */
/* Module definition                                                    */
/* ================================================================== */

static PyMethodDef DwmExtMethods[] = {
    {"enable_dwm_frame",     dwm_enable_frame,         METH_VARARGS,
     "Extend DWM frame into client area (preserves animations for frameless windows)."},
    {"apply_mica",           dwm_apply_mica,           METH_VARARGS,
     "Apply Windows 11 Mica backdrop to HWND."},
    {"apply_acrylic",        dwm_apply_acrylic,        METH_VARARGS,
     "Apply Windows 11 Acrylic backdrop to HWND."},
    {"clear_backdrop",       dwm_clear_backdrop,       METH_VARARGS,
     "Remove DWM backdrop effect from HWND."},
    {"apply_dark_titlebar",  dwm_apply_dark_titlebar,  METH_VARARGS,
     "Set dark (1) or light (0) title bar for HWND."},
    {"apply_rounded",        dwm_apply_rounded,        METH_VARARGS,
     "Apply Windows 11 rounded corners to HWND."},
    {"set_progress",         dwm_set_progress,         METH_VARARGS,
     "Set taskbar progress: (hwnd, completed, total)."},
    {"clear_progress",       dwm_clear_progress,       METH_VARARGS,
     "Remove taskbar progress bar from HWND."},
    {"set_progress_state",   dwm_set_progress_state,   METH_VARARGS,
     "Set taskbar progress state: 0=none, 2=normal, 8=paused."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef dwm_ext_module = {
    PyModuleDef_HEAD_INIT,
    "dwm_ext",
    "Windows DWM + Taskbar native extension (MSYS2 GCC build)",
    -1,
    DwmExtMethods
};

PyMODINIT_FUNC
PyInit_dwm_ext(void)
{
    PyObject *m = PyModule_Create(&dwm_ext_module);
    if (!m) return NULL;

    /* Progress state constants */
    PyModule_AddIntConstant(m, "TBPF_NOPROGRESS", 0);
    PyModule_AddIntConstant(m, "TBPF_NORMAL", 2);
    PyModule_AddIntConstant(m, "TBPF_PAUSED", 8);
    PyModule_AddIntConstant(m, "TBPF_ERROR", 4);

    return m;
}
