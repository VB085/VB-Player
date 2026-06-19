#!/usr/bin/env python3
import os
import sys
import sysconfig
from pathlib import Path

# If the project .venv exists but we're not running from it, re-exec with venv Python
_PROJECT_VENV = Path(__file__).resolve().parent / ".venv"

# Resolve venv Python binary (python3, python, python.exe on Windows)
if sys.platform == "win32":
    _venv_bin = _PROJECT_VENV / "Scripts"
    _candidates = ["python.exe"]
else:
    _venv_bin = _PROJECT_VENV / "bin"
    _candidates = ["python3", "python"]
_VENV_PYTHON = None
for _name in _candidates:
    _candidate = _venv_bin / _name
    if _candidate.exists():
        _VENV_PYTHON = _candidate
        break

# Detect if we're running from the project venv (compare prefix, not executable
# path — venv symlinks may point to the same system python).
_in_venv = (str(Path(sys.prefix).resolve()) == str(_PROJECT_VENV.resolve()))

if not _in_venv and _VENV_PYTHON:
    os.environ["VIRTUAL_ENV"] = str(_PROJECT_VENV)
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), __file__] + sys.argv[1:])

# Ensure bundled Qt6 libraries are found before system ones
_venv = os.environ.get("VIRTUAL_ENV", str(Path(__file__).parent / ".venv"))

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



# --- Single-instance lock via fcntl (kernel-enforced, survives crashes) ---
import fcntl
_LOCK_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "vbplayer.lock"
_LOCK_FD = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
try:
    fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("VB Player is already running.", file=sys.stderr)
    os.close(_LOCK_FD)
    sys.exit(0)
# _LOCK_FD stays open for the lifetime of the process; kernel auto-releases on exit


# First-run: install missing platform dependencies (system media controls, etc.)
from audio_player.bootstrap import ensure_dependencies
ensure_dependencies()

from audio_player.app import create_app
from audio_player.main_window import MainWindow


def main():
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
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
