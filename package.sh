#!/usr/bin/env bash
# VB Player — Package: .deb + .AppImage
set -e
cd "$(dirname "$0")"

BIN_DIR="dist/VB Player"
BIN="$BIN_DIR/VB Player"
VERSION="0.6.1"
_RAW_ARCH="$(uname -m)"
case "$_RAW_ARCH" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    armv7l)  ARCH="armhf" ;;
    *)       ARCH="$_RAW_ARCH" ;;
esac
MODE="${1:-all}"

if [ ! -f "$BIN" ]; then
    echo "Binary not found at '$BIN'. Run ./build.sh first."
    exit 1
fi

build_deb() {
    echo "=== Building .deb ==="
    DEB="dist/vb-player_${VERSION}_${ARCH}"
    rm -rf "$DEB"
    mkdir -p "$DEB/DEBIAN"
    mkdir -p "$DEB/usr/bin"
    mkdir -p "$DEB/usr/share/applications"
    mkdir -p "$DEB/usr/share/icons/hicolor/256x256/apps"
    mkdir -p "$DEB/usr/share/vb-player"

    cp -r "$BIN_DIR"/* "$DEB/usr/share/vb-player/"

    cat > "$DEB/usr/bin/vb-player" << 'EOF'
#!/bin/bash
exec "/usr/share/vb-player/VB Player" "$@"
EOF
    chmod +x "$DEB/usr/bin/vb-player"

    cp assets/vb-player.desktop "$DEB/usr/share/applications/" 2>/dev/null || true
    cp assets/vb-player.png "$DEB/usr/share/icons/hicolor/256x256/apps/" 2>/dev/null || true

    cat > "$DEB/DEBIAN/control" << EOF
Package: vb-player
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: ${ARCH}
Depends: libc6, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, gstreamer1.0-alsa, python3-gi, gir1.2-gstreamer-1.0
Maintainer: VB085
Description: Cross-platform HiFi audio player
 VB Player is a PyQt6 desktop audio player with spectrum visualization,
 album management, LRC lyrics, DLNA casting, equalizer and DSD support.
EOF

    dpkg-deb --root-owner-group --build "$DEB" "dist/vb-player_${VERSION}_${ARCH}.deb"
    ls -lh "dist/vb-player_${VERSION}_${ARCH}.deb"
}

build_appimage() {
    echo "=== Building .AppImage ==="
    APPDIR="dist/VB_Player.AppDir"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR"
    cp -r "$BIN_DIR"/* "$APPDIR/"

    cp assets/vb-player.desktop "$APPDIR/" 2>/dev/null || true
    cp assets/vb-player.png "$APPDIR/vb-player.png" 2>/dev/null || true
    cp assets/vb-player.png "$APPDIR/.DirIcon" 2>/dev/null || true

    cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/VB Player" "$@"
EOF
    chmod +x "$APPDIR/AppRun"

    APPIMAGE="dist/VB_Player-v${VERSION}-${ARCH}.AppImage"
    if command -v appimagetool &>/dev/null; then
        appimagetool "$APPDIR" "$APPIMAGE"
    else
        wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage" -O /tmp/at 2>/dev/null || true
        if [ -s /tmp/at ]; then
            chmod +x /tmp/at && /tmp/at "$APPDIR" "$APPIMAGE"
        else
            echo "appimagetool not available. Making portable tar.gz instead."
            tar czf "dist/VB_Player-v${VERSION}-${ARCH}-portable.tar.gz" -C dist VB_Player.AppDir
            ls -lh "dist/VB_Player-v${VERSION}-${ARCH}-portable.tar.gz"
            return
        fi
    fi
    chmod +x "$APPIMAGE"
    ls -lh "$APPIMAGE"
}

case "$MODE" in
    --deb)      build_deb ;;
    --appimage) build_appimage ;;
    all)        build_deb; build_appimage ;;
esac

echo "Done."
