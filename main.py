#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Ensure bundled Qt6 libraries are found before system ones
_venv = os.environ.get("VIRTUAL_ENV", str(Path(__file__).parent / ".venv"))
_qt6_lib = Path(_venv) / "lib" / "python3.14" / "site-packages" / "PyQt6" / "Qt6" / "lib"
# Also try generic site-packages path
if not _qt6_lib.exists():
    import site
    for sp in site.getsitepackages():
        _candidate = Path(sp) / "PyQt6" / "Qt6" / "lib"
        if _candidate.exists():
            _qt6_lib = _candidate
            break

if _qt6_lib.exists():
    os.environ["LD_LIBRARY_PATH"] = str(_qt6_lib) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")

from audio_player.app import create_app
from audio_player.main_window import MainWindow


def main():
    app = create_app()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
