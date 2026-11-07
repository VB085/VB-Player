# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('D:/Claude/coder/VB-Player/audio_player/ui/themes', 'audio_player/ui/themes'), ('D:/Claude/coder/VB-Player/audio_player/i18n', 'audio_player/i18n'), ('D:/Claude/coder/VB-Player/assets/fonts', 'assets/fonts'), ('C:/msys64/mingw64/lib/gstreamer-1.0', 'lib/gstreamer-1.0')]
binaries = [('D:/Claude/coder/VB-Player/audio_player/platform/windows/dwm_ext.pyd', 'audio_player/platform/windows')]
hiddenimports = ['gi', 'gi.repository.Gst', 'gi.repository.GLib', 'gi.repository.GObject', 'winsdk', 'winsdk.windows.media', 'winsdk.windows.media.playback', 'winsdk.windows.storage.streams']
hiddenimports += collect_submodules('audio_player')
tmp_ret = collect_all('winsdk')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['D:/Claude/coder/VB-Player/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pandas'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VB-Player-MSYS2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VB-Player-MSYS2',
)
