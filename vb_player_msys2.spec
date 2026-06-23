# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VB Player (MSYS2 build with full GStreamer/ASIO/DSD)."""

import sys
from pathlib import Path

_PROJ = Path(SPECPATH)
_MINGW = Path("C:/msys64/mingw64")

a = Analysis(
    ['main.py'],
    pathex=[str(_PROJ)],
    binaries=[],
    datas=[
        # QSS themes
        ('audio_player/ui/themes', 'audio_player/ui/themes'),
        # i18n translations
        ('audio_player/i18n', 'audio_player/i18n'),
        # Fonts
        ('assets/fonts', 'assets/fonts'),
        # GStreamer plugins (241 .dll files)
        (str(_MINGW / 'lib/gstreamer-1.0'), 'lib/gstreamer-1.0'),
    ],
    hiddenimports=[
        'gi', 'gi.repository.Gst', 'gi.repository.GLib', 'gi.repository.GObject',
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
        'numpy', 'mutagen', 'winsdk', 'winsdk.windows.media',
        'winsdk.windows.media.playback', 'winsdk.windows.storage.streams',
        'audio_player', 'audio_player.platform', 'audio_player.platform.windows',
        'audio_player.platform.windows.dwm_ext',
        'ctypes', 'struct', 'json', 'hashlib', 'sqlite3', 'queue',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pandas', 'scipy', 'PIL', 'Pillow'],
)

# Bundle GStreamer core DLLs and their dependencies
_gst_bin = _MINGW / 'bin'
_gst_dlls = []
for _pat in ['libgst*.dll', 'libgobject-2.0-0.dll', 'libglib-2.0-0.dll',
             'libgio-2.0-0.dll', 'libgmodule-2.0-0.dll', 'libintl-8.dll',
             'liborc-0.*.dll', 'libffi-8.dll', 'libpcre2-8-0.dll',
             'zlib1.dll', 'libstdc++-6.dll', 'libgcc_s_seh-1.dll',
             'libwinpthread-1.dll', 'libiconv-2.dll', 'libxml2-*.dll',
             'libsoup-*.dll', 'libsqlite3-0.dll', 'libpng16-16.dll',
             'libjpeg-8.dll', 'libcrypto-*.dll', 'libssl-*.dll',
             'libpsl-5.dll', 'libbrotli*.dll', 'libogg-0.dll',
             'libvorbis-0.dll', 'libvorbisenc-2.dll', 'libFLAC-*.dll',
             'libmp3lame-*.dll', 'libmpg123-*.dll', 'libopus-0.dll',
             'libfaad-*.dll', 'libopenmpt-*.dll', 'libspeex-*.dll',
             'libwavpack-*.dll', 'libgnutls-*.dll', 'libnettle-*.dll',
             'libidn2-*.dll', 'libunistring-*.dll', 'libtasn1-*.dll',
             'libgmp-*.dll', 'libhogweed-*.dll', 'libproxy-*.dll',
             'libduktape-*.dll', 'libsrtp-*.dll', 'libnice-*.dll',
             'libwebrtc-*.dll', 'libopenh264-*.dll', 'libx264-*.dll',
             'libx265-*.dll', 'libdav1d-*.dll', 'librtmp-*.dll',
             'libfftw3-*.dll', 'libsamplerate-*.dll', 'libsndfile-*.dll',
             'libpango*-*.dll', 'libcairo*-*.dll', 'libgdk_pixbuf-*.dll',
             'libpixman-1-*.dll', 'libharfbuzz-*.dll', 'libfribidi-*.dll',
             'libfreetype-*.dll', 'libfontconfig-*.dll', 'libexpat-*.dll',
             'libbz2-*.dll', 'liblzma-*.dll', 'libzstd-*.dll',
             'libdatrie-*.dll', 'libthai-*.dll', 'libgraphite2-*.dll',
             'libepoxy-*.dll', 'libatk-1.0-*.dll', 'libgio-2.0-*.dll',
             'libcairo-gobject-*.dll', 'libcairo-script-interpreter-*.dll',
             ]:
    for _f in _gst_bin.glob(_pat):
        _gst_dlls.append((str(_f), '.'))

# Add our C extension
_dwm = _PROJ / 'audio_player/platform/windows/dwm_ext.pyd'
if _dwm.exists():
    _gst_dlls.append((str(_dwm), 'audio_player/platform/windows'))

a.binaries += _gst_dlls

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='VB Player',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_PROJ / 'assets/vb-player.png'),
)
