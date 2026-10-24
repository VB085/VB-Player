#!/usr/bin/env python3
import os, sys, sysconfig, traceback, signal, faulthandler
from pathlib import Path
# PyInstaller --windowed: stderr can be None
if sys.stderr is None or not sys.stderr:
    sys.stderr = open(os.devnull, "w")
    sys.stdout = sys.stderr

# --- Crash log: tee stderr/stdout to %TEMP%/vbplayer.log (unfrozen builds) ---
# Launching without a console (double-click / pythonw) hid every traceback
# and Qt fatal message. The log makes any crash diagnosable.
_LOG_PATH = Path(os.environ.get("TEMP", os.getcwd())) / "vbplayer.log"
try:
    _log_fp = open(_LOG_PATH, "w", buffering=1, encoding="utf-8", errors="replace")

    class _Tee:
        def __init__(self, *streams):
            self._streams = streams
        def write(self, s):
            for st in self._streams:
                try:
                    st.write(s)
                except Exception:
                    pass
        def flush(self):
            for st in self._streams:
                try:
                    st.flush()
                except Exception:
                    pass
        def isatty(self):
            return False
        def fileno(self):
            # faulthandler needs a real fd — route native dumps to the log
            # file (last stream), so hangs always leave stacks on disk
            return self._streams[-1].fileno()

    sys.stderr = _Tee(sys.stderr, _log_fp)
    sys.stdout = _Tee(sys.stdout, _log_fp)
except Exception:
    _log_fp = None

# faulthandler must be enabled AFTER the tee so native aborts land in the log
faulthandler.enable(file=_log_fp) if _log_fp else faulthandler.enable()

# Catch SIGABRT — exit cleanly instead of core dump (Qt 6.11 QThread bug)
def _abort_handler(signum, frame):
    print("\nSIGABRT caught — exiting cleanly", file=sys.stderr)
    try:
        faulthandler.dump_traceback(file=_log_fp) if _log_fp else faulthandler.dump_traceback()
    except Exception:
        pass
    os._exit(0)

signal.signal(signal.SIGABRT, _abort_handler)

# Global Qt message handler to catch Qt warnings and prevent fatal abort
def _qt_message_handler(mode, context, message):
    if mode == QtMsgType.QtFatalMsg:
        sys.stderr.write(f"\n!!! Qt FATAL — {message}\n")
        sys.stderr.write(f"    file={context.file!r} line={context.line} func={context.function!r}\n")
        sys.stderr.flush()
        traceback.print_stack(file=sys.stderr)
        sys.stderr.flush()
        os._exit(0)  # clean exit, prevent Qt's abort() + core dump
    elif "QThread" in message:
        print(f"[Qt WARNING] {message}", file=sys.stderr)
    # Suppress noisy parse warnings triggered on every repaint
    elif "Could not parse" not in message:
        print(f"[Qt:{mode}] {message}", file=sys.stderr)

# If a project venv exists but we're not running from it, re-exec with venv Python.
# Prefer .venv_msvc (MSVC toolchain, used for development); fall back to .venv.
# A venv whose base interpreter (pyvenv.cfg "home") is missing is skipped —
# e.g. after an OS reinstall the MSYS2-based .venv points to a dead C:\msys64.
def _pick_project_venv_python() -> "Path | None":
    for name in (".venv_msvc", ".venv"):
        root = Path(__file__).resolve().parent / name
        cfg = root / "pyvenv.cfg"
        if not cfg.is_file():
            continue
        home = None
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                if line.startswith("home"):
                    home = Path(line.split("=", 1)[1].strip())
                    break
        except OSError:
            continue
        if home is None or not home.is_dir():
            continue  # base interpreter gone — venv unusable
        if sys.platform == "win32":
            candidates = [root / "Scripts" / "python.exe", root / "bin" / "python.exe"]
        else:
            candidates = [root / "bin" / "python3", root / "bin" / "python"]
        for cand in candidates:
            if cand.exists():
                return cand
    return None

_VENV_PYTHON = _pick_project_venv_python()

# Only re-exec via project venv if NOT already in any virtual environment
_in_any_venv = sys.prefix != sys.base_prefix
_venv_root = _VENV_PYTHON.parent.parent if _VENV_PYTHON else None
_in_venv = bool(_venv_root and
                str(Path(sys.prefix).resolve()) == str(_venv_root.resolve()))

if not _in_any_venv and not _in_venv and _VENV_PYTHON:
    os.environ["VIRTUAL_ENV"] = str(_venv_root)
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), __file__] + sys.argv[1:])

# Ensure bundled Qt6 libraries are found before system ones
_venv = os.environ.get("VIRTUAL_ENV",
                       str(_venv_root or Path(__file__).parent / ".venv"))

# Dynamically determine Python version subdirectory (e.g. "python3.14")
_py_ver = f"python{sysconfig.get_config_var('py_version_nodot')}"

# Qt6 shared libraries live in "lib" on Linux, "bin" on Windows
_qt6_subdir = "bin" if sys.platform == "win32" else "lib"

_qt6_lib = Path(_venv) / "lib" / _py_ver / "site-packages" / "PyQt6" / "Qt6" / _qt6_subdir

if not _qt6_lib.exists():
    import site
    for sp in site.getsitepackages():
        _candidate = Path(sp) / "PyQt6" / "Qt6" / _qt6_subdir
        if _candidate.exists():
            _qt6_lib = _candidate
            break

if _qt6_lib.exists():
    if sys.platform == "win32":
        os.add_dll_directory(str(_qt6_lib))
        os.environ["PATH"] = str(_qt6_lib) + os.pathsep + os.environ.get("PATH", "")
    else:
        os.environ["LD_LIBRARY_PATH"] = str(_qt6_lib) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")



# --- Initialize GStreamer BEFORE Qt (prevents GLib threads being mistaken for QThread) ---
try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)
except Exception:
    pass

# PyInstaller --windowed: always redirect stderr to a log file
# Force log file — unconditionally in PyInstaller builds
if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False) or not sys.stderr:
    try:
        _log = open(os.path.join(os.path.dirname(sys.executable), 'vbplayer.log'), 'w')
        _log.write('PYTHON STARTED\n'); _log.flush()
        sys.stderr, sys.stdout = _log, _log
    except Exception:
        pass

# --- Single-instance lock ---
import tempfile as _tempfile
_LOCK_FILE = Path(_tempfile.gettempdir()) / "vbplayer.lock"
_LOCK_FD = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
if sys.platform == "win32":
    import msvcrt
    os.write(_LOCK_FD, b"0")
    os.lseek(_LOCK_FD, 0, os.SEEK_SET)  # reset to start before locking
    try:
        msvcrt.locking(_LOCK_FD, msvcrt.LK_NBLCK, 1)
    except OSError:
        print("VB Player is already running.", file=sys.stderr)
        os.close(_LOCK_FD)
        sys.exit(0)
else:
    import fcntl
    _LOCK_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "vbplayer.lock"
    _LOCK_FD = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("VB Player is already running.", file=sys.stderr)
        os.close(_LOCK_FD)
        sys.exit(0)


# First-run: install missing platform dependencies (skip in frozen exe)
if not getattr(sys, 'frozen', False):
    from audio_player.bootstrap import ensure_dependencies
    ensure_dependencies()

# PyInstaller: use system MSYS2 GStreamer (bundling all DLLs is not practical)
if getattr(sys, 'frozen', False):
    for _msys2_root in (Path(os.environ.get("MSYSTEM_PREFIX", "")),
                         Path("C:/msys64/mingw64")):
        _msys2_bin = _msys2_root / "bin"
        if _msys2_bin.is_dir():
            os.add_dll_directory(str(_msys2_bin))
            os.environ["PATH"] = str(_msys2_bin) + os.pathsep + os.environ.get("PATH", "")
            os.environ['GST_PLUGIN_PATH'] = str(_msys2_root / "lib" / "gstreamer-1.0")
            break

# Install Qt message handler
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
qInstallMessageHandler(_qt_message_handler)

from audio_player.app import create_app
from audio_player.main_window import MainWindow


def main():
    import threading
    import time
    import traceback
    _orig_excepthook = sys.excepthook

    def _excepthook(typ, val, tb):
        from PyQt6.QtWidgets import QMessageBox
        msg = "".join(traceback.format_exception(typ, val, tb))
        print(msg, file=sys.stderr)
        QMessageBox.critical(None, "VB Player Error", msg)
        _orig_excepthook(typ, val, tb)

    sys.excepthook = _excepthook

    app = create_app()
    # tooltips: off by default, 1.2s hover delay when on (settings → show_tooltips)
    from audio_player.ui.tooltip_gate import install_tooltip_gate
    install_tooltip_gate(app)
    window = MainWindow()

    # --- Hang watchdog: Windows reports this app as AppHangB1 (main thread
    # stops pumping events ≥5 s). An independent thread watches a heartbeat
    # bumped by a Qt timer; when the GUI thread freezes it dumps every
    # thread's stack to the crash log so the freeze site is recorded.
    _hb = {"t": time.time()}
    from PyQt6.QtCore import QTimer
    _hb_timer = QTimer(app)
    _hb_timer.setInterval(500)
    _hb_timer.timeout.connect(lambda: _hb.__setitem__("t", time.time()))
    _hb_timer.start()
    _last_dump = [0]

    def _watchdog():
        while True:
            try:
                time.sleep(2)
                lag = time.time() - _hb["t"]
                if lag > 5.0:
                    gen = int(lag // 5.0)
                    if gen > _last_dump[0]:
                        _last_dump[0] = gen
                        print(f"\n=== HANG DETECTED: GUI thread unresponsive {lag:.1f}s — stack dump ===",
                              file=sys.stderr)
                        sys.stderr.flush()
                        try:
                            faulthandler.dump_traceback(file=_log_fp if _log_fp else sys.stderr)
                        except Exception:
                            faulthandler.dump_traceback()
            except Exception:
                pass  # the watchdog must survive to dump again on the next hang

    threading.Thread(target=_watchdog, daemon=True, name="hang-watchdog").start()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
