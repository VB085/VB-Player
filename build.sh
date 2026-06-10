#!/usr/bin/env bash
# VB Player — Cross-platform build script
# Usage: ./build.sh [--onefile] [--debug]

set -e
cd "$(dirname "$0")"

MODE="dir"
DEBUG=""
for arg in "$@"; do
    case "$arg" in
        --onefile) MODE="onefile" ;;
        --debug)   DEBUG="--debug" ;;
    esac
done

echo "=== VB Player Build ==="
echo "Platform: $(uname -s) $(uname -m)"
echo "Python:   $(python --version 2>&1)"
echo "Mode:     $MODE"
echo ""

# Clean previous build
rm -rf build/ dist/

if [ "$MODE" = "onefile" ]; then
    echo "[1/2] Building single-file executable..."
    pyinstaller vb_player.spec \
        --onefile \
        --noconfirm \
        $DEBUG \
        2>&1
    echo ""
    echo "[2/2] Done!"
    echo "Output: dist/VB Player"
    ls -lh dist/VB\ Player 2>/dev/null || true
else
    echo "[1/2] Building directory bundle..."
    pyinstaller vb_player.spec \
        --noconfirm \
        $DEBUG \
        2>&1
    echo ""
    echo "[2/2] Done!"
    echo "Output: dist/VB Player/"
    ls -la dist/VB\ Player/ 2>/dev/null | head -20 || true
fi

echo ""
echo "=== Build complete ==="
