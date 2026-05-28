#!/usr/bin/env python3
import os
import sys
import sysconfig
from pathlib import Path

# If the project .venv exists but we're not running from it, re-exec with venv Python
_PROJECT_VENV = Path(__file__).resolve().parent / ".venv"
_VENV_PYTHON = _PROJECT_VENV / ("Scripts" if sys.platform == "win32" else "bin") / "python.exe"
if not _VENV_PYTHON.exists():
    _VENV_PYTHON = _PROJECT_VENV / "bin" / "python.exe"  # MSYS2/MinGW venv layout
if _VENV_PYTHON.exists() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
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
