#!/usr/bin/env bash
# VB Player — Cross-platform build & package
# Usage:
#   ./build.sh              # directory bundle (quick test)
#   ./build.sh --onefile    # single executable
#   ./build.sh --package    # platform package (AppImage/dmg/msi)
set -e
cd "$(dirname "$0")"

PLATFORM="$(uname -s)"
ARCH="$(uname -m)"
MODE="dir"
PACKAGE=0

for arg in "$@"; do
    case "$arg" in
        --onefile) MODE="onefile" ;;
        --dir)     MODE="dir" ;;
        --package) PACKAGE=1 ;;
        --debug)   DEBUG="--debug" ;;
    esac
done

echo "=== VB Player v0.6 Build ==="
echo "Platform: $PLATFORM $ARCH"
echo "Mode:     $MODE"
echo "Package:  $PACKAGE"
echo ""

# Ensure venv
if [ ! -d .venv ]; then
    echo "Creating venv..."
    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install PyQt6 numpy mutagen qtawesome pyinstaller
fi

# Use venv python
PYTHON=".venv/bin/python"

# Clean
rm -rf build/ dist/

# ── PyInstaller build ──
EXTRA_DATAS=()

# Platform-specific hidden imports
case "$PLATFORM" in
    Linux)
        HIDDEN_IMPORTS="PyQt6.QtDBus"
        ;;
    Darwin)
        HIDDEN_IMPORTS=""
        EXTRA_DATAS+=("--add-data" "audio_player/platform/macos:audio_player/platform/macos")
        ;;
    MINGW*|MSYS*|CYGWIN*|Windows)
        PLATFORM="Windows"
        HIDDEN_IMPORTS=""
        EXTRA_DATAS+=("--add-data" "audio_player/platform/windows:audio_player/platform/windows")
        ;;
esac

echo "[1/2] Building with PyInstaller..."

# Build hidden import string
HIDDEN_FLAGS=()
for imp in PyQt6.QtMultimedia mutagen mutagen.mp3 mutagen.flac mutagen.oggopus \
           mutagen.oggvorbis mutagen.mp4 mutagen.id3 mutagen.aac numpy qtawesome \
           $HIDDEN_IMPORTS; do
    HIDDEN_FLAGS+=("--hidden-import=$imp")
done

# Add i18n JSON files
I18N_DIR="audio_player/i18n"
for f in "$I18N_DIR"/*.json; do
    EXTRA_DATAS+=("--add-data" "$f:${I18N_DIR}")
done

# Add themes
EXTRA_DATAS+=("--add-data" "audio_player/ui/themes:audio_player/ui/themes")

if [ "$MODE" = "onefile" ]; then
    $PYTHON -m PyInstaller \
        --onefile \
        --name="VB Player" \
        --noconfirm \
        --noconsole \
        "${HIDDEN_FLAGS[@]}" \
        "${EXTRA_DATAS[@]}" \
        --exclude-module tkinter --exclude-module unittest --exclude-module test \
        --exclude-module distutils --exclude-module setuptools --exclude-module pip \
        $DEBUG \
        main.py 2>&1
    echo ""
    echo "[2/2] Done!"
    ls -lh dist/ 2>/dev/null || true
else
    $PYTHON -m PyInstaller \
        --name="VB Player" \
        --noconfirm \
        --noconsole \
        "${HIDDEN_FLAGS[@]}" \
        "${EXTRA_DATAS[@]}" \
        --exclude-module tkinter --exclude-module unittest --exclude-module test \
        --exclude-module distutils --exclude-module setuptools --exclude-module pip \
        $DEBUG \
        main.py 2>&1
    echo ""
    echo "[2/2] Done!"
    echo "Output: dist/VB Player/"
    du -sh dist/VB\ Player/ 2>/dev/null || true
fi

# ── Packaging ──
if [ "$PACKAGE" = "1" ]; then
    echo ""
    echo "=== Packaging ==="
    case "$PLATFORM" in
        Linux)
            echo "→ AppImage (requires appimagetool)"
            # Prepare AppDir
            APPDIR="dist/VB_Player.AppDir"
            rm -rf "$APPDIR"
            mkdir -p "$APPDIR"
            cp -r "dist/VB Player/"* "$APPDIR/"
            cp "assets/vb-player.desktop" "$APPDIR/" 2>/dev/null || true
            cp "assets/vb-player.png" "$APPDIR/" 2>/dev/null || true
            if command -v appimagetool &>/dev/null; then
                appimagetool "$APPDIR" "dist/VB_Player-$ARCH.AppImage"
                echo "AppImage: dist/VB_Player-$ARCH.AppImage"
            else
                echo "Install appimagetool for AppImage packaging"
            fi
            ;;
        Darwin)
            echo "→ DMG (requires create-dmg)"
            if command -v create-dmg &>/dev/null; then
                create-dmg "dist/VB Player.dmg" "dist/VB Player.app" 2>/dev/null || true
                echo "DMG: dist/VB Player.dmg"
            else
                echo "Install create-dmg: brew install create-dmg"
            fi
            ;;
        Windows)
            echo "→ Windows installer (requires Inno Setup)"
            echo "Run Inno Setup Compiler on assets/setup.iss"
            ;;
    esac
fi

echo ""
echo "=== Build complete ==="
