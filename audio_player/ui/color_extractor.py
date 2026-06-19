"""Extract dominant vibrant color from album cover art."""

from collections import Counter

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPixmap, QImage


def extract_accent(pixmap: QPixmap) -> QColor:
    """Extract a vibrant accent color from album cover art.

    Quantizes colors, then picks the most saturated among the dominant
    ones, avoiding black/white/gray.
    """
    if pixmap.isNull():
        return QColor("#7c3aed")

    # Downscale for speed
    scaled = pixmap.scaled(
        100, 100,
        aspectRatioMode=Qt.AspectRatioMode.KeepAspectRatio,
        transformMode=Qt.TransformationMode.SmoothTransformation,
    )
    # RGB888 → [R, G, B] in memory order, no alpha byte-swap issues
    img = scaled.toImage().convertToFormat(QImage.Format.Format_RGB888)

    w, h = img.width(), img.height()
    ptr = img.bits()
    ptr.setsize(w * h * 3)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 3)

    r = arr[..., 0].ravel()
    g = arr[..., 1].ravel()
    b = arr[..., 2].ravel()

    # Skip near-black and near-white
    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    valid = (brightness > 40) & (brightness < 225)
    if valid.sum() > 50:
        r, g, b = r[valid], g[valid], b[valid]

    if len(r) == 0:
        return QColor("#7c3aed")

    # Quantize to 32 levels per channel
    q = 256 // 32
    qr = (r // q) * q
    qg = (g // q) * q
    qb = (b // q) * q

    # Count and score: prefer saturated, frequent colors
    counts = Counter(zip(qr, qg, qb))
    best_color = None
    best_score = -1
    for (cr, cg, cb), count in counts.most_common(200):
        sat = max(cr, cg, cb) - min(cr, cg, cb)
        bright = 0.299 * cr + 0.587 * cg + 0.114 * cb
        if bright < 35 or bright > 225:
            continue
        score = sat * (count ** 0.5)
        if score > best_score:
            best_score = score
            best_color = (cr, cg, cb)

    if best_color is None:
        return QColor("#7c3aed")

    # Output slightly darkened for contrast
    return QColor(
        max(0, int(best_color[0] * 0.85)),
        max(0, int(best_color[1] * 0.85)),
        max(0, int(best_color[2] * 0.85)),
    )
