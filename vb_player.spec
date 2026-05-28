# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VB Player — Linux/Windows/macOS."""

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / 'audio_player' / 'ui' / 'themes' / '*.qss'),
         'audio_player/ui/themes'),
    ],
    hiddenimports=[
        'PyQt6.QtMultimedia',
        'PyQt6.QtDBus',
        'mutagen',
        'mutagen.mp3',
        'mutagen.flac',
        'mutagen.oggopus',
        'mutagen.oggvorbis',
        'mutagen.mp4',
        'mutagen.id3',
        'mutagen.aac',
        'numpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'test', 'distutils',
        'setuptools', 'pip', 'wheel', 'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=False,          # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VB Player',
)
