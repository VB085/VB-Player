"""Centralized icon definitions using QtAwesome (Font Awesome 6 Free)."""
import qtawesome as qta
from PyQt6.QtGui import QIcon, QColor
from audio_player.app import current_accent


def _icon(name: str, color: str = None, **kwargs) -> QIcon:
    """Create a QIcon from a Font Awesome 6 name."""
    return qta.icon(name, color=color, **kwargs)


def _accent_icon(name: str, **kwargs) -> QIcon:
    """Create a QIcon with the current accent color."""
    return qta.icon(name, color=current_accent().name(), **kwargs)


# ── Sidebar navigation ──────────────────────────────────────────────
# Prefix: fa6s = solid, fa6r = regular, fa6b = brands
NAV_SONGS     = "fa6s.list"
NAV_ALBUMS    = "fa6s.compact-disc"
NAV_FAVORITES = "fa6s.star"
NAV_PLAYLISTS = "fa6s.rectangle-list"
NAV_NETWORK   = "fa6s.globe"
NAV_MANAGE    = "fa6s.gear"
NAV_SETTINGS  = "fa6s.wrench"

SIDEBAR_TOGGLE  = "fa6s.bars"
SIDEBAR_EXPAND  = "fa6s.chevron-right"

# ── Transport controls ──────────────────────────────────────────────
TRANSPORT_PREV  = "fa6s.backward-step"
TRANSPORT_PLAY  = "fa6s.play"
TRANSPORT_PAUSE = "fa6s.pause"
TRANSPORT_NEXT  = "fa6s.forward-step"

# ── Playback modes ──────────────────────────────────────────────────
MODE_SEQUENTIAL = "fa6s.play"
MODE_REPEAT_ALL = "fa6s.repeat"
MODE_REPEAT_ONE = "fa6s.arrows-rotate"
MODE_SHUFFLE    = "fa6s.shuffle"
MODE_MORE       = "fa6s.ellipsis"

# ── Volume ──────────────────────────────────────────────────────────
VOLUME_MUTED    = "fa6s.volume-xmark"
VOLUME_LOW      = "fa6s.volume-low"
VOLUME_MEDIUM   = "fa6s.volume-low"
VOLUME_HIGH     = "fa6s.volume-high"

# ── Panel toggle ────────────────────────────────────────────────────
PANEL_COLLAPSE  = "fa6s.chevron-left"
PANEL_EXPAND    = "fa6s.chevron-right"

# ── Misc ────────────────────────────────────────────────────────────
ALBUM_PLACEHOLDER = "fa6s.compact-disc"
IMPORT_FOLDER     = "fa6s.folder-open"
IMPORT_FILES      = "fa6s.file-audio"
RELOAD            = "fa6s.arrows-rotate"
FAVORITE          = "fa6s.star"
FAVORITE_OUTLINE  = "fa6.star"
