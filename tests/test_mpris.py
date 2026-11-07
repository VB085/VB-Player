"""Tests for MPRIS variant handling."""

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from audio_player.player.mpris2 import _as_double


def test_as_double_accepts_variant():
    assert _as_double(GLib.Variant("d", 0.42)) == 0.42


def test_as_double_accepts_unpacked_float():
    # PyGObject >= 3.50 may unpack (ssv) values before the handler sees them.
    assert _as_double(0.42) == 0.42


def test_unpack_metadata_normalizes_variants():
    from audio_player.player.mpris2 import _unpack_metadata

    raw = {
        "title": GLib.Variant("s", "晴天"),
        "duration_ms": GLib.Variant("x", 269000),
        "cover_data": GLib.Variant("ay", b"fake-jpeg"),
    }
    meta = _unpack_metadata(raw)
    assert meta["title"] == "晴天"
    assert meta["duration_ms"] == 269000
    assert meta["cover_data"] == b"fake-jpeg"


def test_open_playlist_method_is_registered():
    from gi.repository import Gio
    from audio_player.player.mpris2 import MPRIS2_XML

    info = Gio.DBusNodeInfo.new_for_xml(MPRIS2_XML)
    iface = info.lookup_interface("org.mpris.MediaPlayer2.Player")
    assert iface.lookup_method("OpenPlaylistWithMetadata") is not None
