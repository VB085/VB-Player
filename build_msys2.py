"""Build script: runs PyInstaller with GStreamer + all deps for MSYS2."""
import subprocess, sys, glob, os
from pathlib import Path

PROJ = Path(__file__).parent
MINGW = Path("C:/msys64/mingw64")
GST_PLUGIN_DIR = MINGW / "lib/gstreamer-1.0"
GST_BIN = MINGW / "bin"
BUILD = PROJ / "build"
DIST = PROJ / "dist"

# Clean build — only our output dirs
import shutil
for d in [DIST, BUILD]:
    if d.exists():
        try:
            shutil.rmtree(d)
        except PermissionError:
            print(f"WARNING: cannot remove {d}, continuing...")

# Collect GStreamer plugin DLLs as data files
plugin_dlls = list(GST_PLUGIN_DIR.glob("*.dll"))
print(f"Found {len(plugin_dlls)} GStreamer plugins")

# Copy MSYS2 runtime DLLs to exe directory AFTER build
_RUNTIME_DLLS = ["libpython3.14.dll", "libgcc_s_seh-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"]

# Collect core GStreamer + dependency DLLs from MSYS2 bin
core_dlls = []
for pattern in [
    "libgst*.dll", "libgobject-2.0-0.dll", "libglib-2.0-0.dll",
    "libgio-2.0-0.dll", "libgmodule-2.0-0.dll",
    "libintl-8.dll", "liborc*.dll", "libffi-8.dll",
    "libpcre2-8-0.dll", "zlib1.dll", "libstdc++-6.dll",
    "libgcc_s_seh-1.dll", "libwinpthread-1.dll", "libiconv-2.dll",
    "libxml2-*.dll", "libsoup-*.dll", "libsqlite3-0.dll",
    "libpng16-16.dll", "libjpeg-8.dll",
    "libogg-0.dll", "libvorbis*.dll", "libFLAC-*.dll",
    "libmp3lame-*.dll", "libmpg123-*.dll", "libopus-0.dll",
    "libfaad-*.dll", "libopenmpt-*.dll", "libspeex-*.dll",
    "libwavpack-*.dll", "libgnutls-*.dll", "libnettle-*.dll",
    "libidn2-*.dll", "libunistring-*.dll", "libtasn1-*.dll",
    "libgmp-*.dll", "libhogweed-*.dll",
    "libbrotli*.dll", "libdatrie-*.dll", "libthai-*.dll",
    "libgraphite2-*.dll", "libepoxy-*.dll",
    "libfreetype-*.dll", "libfontconfig-*.dll", "libexpat-*.dll",
    "libbz2-*.dll", "liblzma-*.dll", "libzstd-*.dll",
    "libfftw3-*.dll", "libsamplerate-*.dll", "libsndfile-*.dll",
    "libpango*-*.dll", "libcairo*.dll",
    "libgdk_pixbuf-*.dll", "libpixman-1-*.dll",
    "libharfbuzz-*.dll", "libfribidi-*.dll",
]:
    core_dlls.extend(GST_BIN.glob(pattern))
print(f"Found {len(core_dlls)} core GStreamer DLLs")

# Build command
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--onedir", "--windowed",
    "--name", "VB-Player-MSYS2",
    "--distpath", str(PROJ / "dist"),
    # "--icon", str(PROJ / "assets/vb-player.png"),  # skip: PNG not supported without Pillow
    # Source
    str(PROJ / "main.py"),
    # QSS themes
    "--add-data", f"{PROJ / 'audio_player/ui/themes'}{os.pathsep}audio_player/ui/themes",
    # i18n
    "--add-data", f"{PROJ / 'audio_player/i18n'}{os.pathsep}audio_player/i18n",
    # Fonts
    "--add-data", f"{PROJ / 'assets/fonts'}{os.pathsep}assets/fonts",
    # GStreamer plugins as data
    "--add-data", f"{GST_PLUGIN_DIR}{os.pathsep}lib/gstreamer-1.0",
    # C extension
    "--add-binary", f"{PROJ / 'audio_player/platform/windows/dwm_ext.pyd'}{os.pathsep}audio_player/platform/windows",
    # Hidden imports
    "--hidden-import", "gi",
    "--hidden-import", "gi.repository.Gst",
    "--hidden-import", "gi.repository.GLib",
    "--hidden-import", "gi.repository.GObject",
    "--hidden-import", "winsdk",
    "--hidden-import", "winsdk.windows.media",
    "--hidden-import", "winsdk.windows.media.playback",
    "--hidden-import", "winsdk.windows.storage.streams",
    "--collect-all", "winsdk",
    "--collect-submodules", "audio_player",
    # Exclude
    "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib",
    "--exclude-module", "pandas",
]

# Add MSYS2 path for DLL discovery
env = os.environ.copy()
env["PATH"] = str(GST_BIN) + os.pathsep + env.get("PATH", "")

print(f"\nBuilding with {' '.join(cmd[:6])}...")
result = subprocess.run(cmd, cwd=str(PROJ), env=env, capture_output=False)
# Copy MSYS2 runtime DLLs next to the exe (PyInstaller doesn't put them there)
import shutil as _shutil
for _dll in _RUNTIME_DLLS:
    _src = GST_BIN / _dll
    if _src.exists():
        _shutil.copy2(_src, DIST / "VB-Player-MSYS2" / _src.name)
        print(f"  Copied {_src.name}")

if result.returncode == 0:
    exe = DIST / "VB-Player-MSYS2/VB-Player-MSYS2.exe"
    if exe.exists():
        import stat
        print(f"\nBuild successful: {exe}")
        print(f"Size: {exe.stat().st_size / 1024**2:.0f} MB")
else:
    print(f"\nBuild failed with code {result.returncode}")
