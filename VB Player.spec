# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('audio_player/i18n/en.json', 'audio_player/i18n'), ('audio_player/i18n/ja.json', 'audio_player/i18n'), ('audio_player/i18n/zh_CN.json', 'audio_player/i18n'), ('audio_player/i18n/zh_TW.json', 'audio_player/i18n'), ('audio_player/ui/themes', 'audio_player/ui/themes')],
    hiddenimports=['PyQt6.QtMultimedia', 'mutagen', 'mutagen.mp3', 'mutagen.flac', 'mutagen.oggopus', 'mutagen.oggvorbis', 'mutagen.mp4', 'mutagen.id3', 'mutagen.aac', 'numpy', 'qtawesome', 'PyQt6.QtDBus'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test', 'distutils', 'setuptools', 'pip'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VB Player',
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
    name='VB Player',
)
