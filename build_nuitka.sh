#!/usr/bin/env bash
# VB Player — Nuitka build (faster runtime than PyInstaller)
# Usage: ./build_nuitka.sh [--standalone] [--onefile]
#
# Prerequisites:
#   pip install nuitka ordered-set
#   # Nuitka needs a C compiler: gcc/clang on Linux, MSVC on Windows

set -e
cd "$(dirname "$0")"

MODE="--standalone"
for arg in "$@"; do
    case "$arg" in
        --onefile)    MODE="--onefile" ;;
        --standalone) MODE="--standalone" ;;
    esac
done

echo "=== VB Player Nuitka Build ==="
echo "Platform: $(uname -s) $(uname -m)"
echo "Python:   $(python --version 2>&1)"
echo "Mode:     $MODE"
echo ""

# Clean
rm -rf build/VB_Player.dist build/VB_Player.build main.dist

echo "Building with Nuitka..."
python -m nuitka \
    $MODE \
    --output-filename="VB Player" \
    --output-dir=build \
    --include-data-dir=audio_player/ui/themes=audio_player/ui/themes \
    --include-package=mutagen \
    --include-package=PyQt6.QtMultimedia \
    --enable-plugin=pyqt6 \
    --nofollow-import-to=tkinter,unittest,test,distutils,setuptools,pip,wheel,pytest \
    --assume-yes-for-downloads \
    --remove-output \
    main.py \
    2>&1

echo ""
echo "=== Build complete ==="
if [ "$MODE" = "--onefile" ]; then
    ls -lh build/VB\ Player 2>/dev/null || ls -lh build/main.dist 2>/dev/null || true
else
    du -sh build/VB_Player.dist/ 2>/dev/null || du -sh build/main.dist/ 2>/dev/null || true
fi
