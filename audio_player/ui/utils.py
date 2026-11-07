"""Shared utility functions used across UI widgets."""

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPixmap
from audio_player.app import current_theme_mode

_cached_cover_radius: int | None = None


def center_square(pixmap: QPixmap) -> QPixmap:
    """居中裁出最大正方形。

    非方形图直接 KeepAspectRatio 缩放进方形/圆形框会留透明边（色带），
    先居中裁方再缩放即可铺满。"""
    w, h = pixmap.width(), pixmap.height()
    side = min(w, h)
    if side <= 0:
        return pixmap
    return pixmap.copy((w - side) // 2, (h - side) // 2, side, side)


def fill_cover_image(source: QImage, size: int, radius: int) -> QImage:
    """封面铺满 size×size 圆角图（ByExpanding 居中裁切 + 圆角蒙版）。

    统一各处封面缩放：KeepAspectRatio 在非方形封面上会留边、露出底色
    形成黑框/色带；drawImage 画在 (0,0) 会造成偏侧空隙。返回 QImage
    （ARGB32），可在工作线程安全使用。
    """
    if source.isNull():
        return source
    scaled = source.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    out = QImage(size, size, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    pt = QPainter(out)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(size), float(size),
                        float(radius), float(radius))
    pt.setClipPath(path)
    pt.drawImage((size - scaled.width()) // 2,
                 (size - scaled.height()) // 2, scaled)
    pt.end()
    return out


def cover_radius_enabled() -> bool:
    return cover_corner_radius() > 0


def cover_corner_radius() -> int:
    global _cached_cover_radius
    if _cached_cover_radius is not None:
        return _cached_cover_radius
    try:
        s = QSettings("VBPlayer", "VB Player")
        enabled = str(s.value("album_cover_radius", "true")).lower() == "true"
        _cached_cover_radius = 8 if enabled else 0
    except Exception:
        _cached_cover_radius = 8
    return _cached_cover_radius


def refresh_cover_radius_cache():
    """Invalidate cached cover radius — call on settings change."""
    global _cached_cover_radius
    _cached_cover_radius = None


def format_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS, M:SS, or --:--."""
    if seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def is_light_mode() -> bool:
    """Return True when the current theme mode is 'light'."""
    return current_theme_mode() == "light"
