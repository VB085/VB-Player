"""MPRIS2 D-Bus service for Linux desktop media controls."""

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_player.player._types import PlaybackState
from audio_player.player.metadata import read_metadata

try:
    from gi.repository import Gio, GLib
except ImportError:
    raise ImportError("PyGObject (gi.repository) is required for MPRIS2 support")

MPRIS2_BUS_NAME = "org.mpris.MediaPlayer2.vbplayer"
MPRIS2_OBJECT_PATH = "/org/mpris/MediaPlayer2"

MPRIS2_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg direction="in" name="Offset" type="x"/>
    </method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""

_INTERFACE_INFO = Gio.DBusNodeInfo.new_for_xml(MPRIS2_XML)
_IFACE_PLAYER = _INTERFACE_INFO.lookup_interface("org.mpris.MediaPlayer2.Player")
_IFACE_ROOT = _INTERFACE_INFO.lookup_interface("org.mpris.MediaPlayer2")
_IFACE_PROPERTIES = Gio.DBusNodeInfo.new_for_xml(
    '<node><interface name="org.freedesktop.DBus.Properties">'
    '<method name="Get"><arg direction="in" name="interface" type="s"/>'
    '<arg direction="in" name="property" type="s"/>'
    '<arg direction="out" name="value" type="v"/></method>'
    '<method name="Set"><arg direction="in" name="interface" type="s"/>'
    '<arg direction="in" name="property" type="s"/>'
    '<arg direction="in" name="value" type="v"/></method>'
    '<method name="GetAll"><arg direction="in" name="interface" type="s"/>'
    '<arg direction="out" name="properties" type="a{sv}"/></method>'
    '<signal name="PropertiesChanged"><arg name="interface" type="s"/>'
    '<arg name="changed_properties" type="a{sv}"/>'
    '<arg name="invalidated_properties" type="as"/></signal>'
    '</interface></node>'
).lookup_interface("org.freedesktop.DBus.Properties")

_STATUS_MAP = {
    PlaybackState.Stopped: "Stopped",
    PlaybackState.Playing: "Playing",
    PlaybackState.Paused: "Paused",
}

_SUPPORTED_MIMES = [
    "audio/mpeg", "audio/flac", "audio/ogg", "audio/opus",
    "audio/mp4", "audio/x-wav", "audio/x-aiff", "audio/x-ape",
    "audio/x-wavpack", "audio/x-dsf",
]


def _cover_temp_path() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(xdg) if xdg else Path(tempfile.gettempdir())
    return base / "vbplayer_cover.jpg"


class Mpris2Service(QObject):
    """MPRIS2 D-Bus service for Linux desktop media controls."""

    raiseRequested = pyqtSignal()
    quitRequested = pyqtSignal()

    def __init__(self, engine, controller, playlist, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._controller = controller
        self._playlist = playlist
        self._connection: Gio.DBusConnection | None = None
        self._owner_id = 0
        self._registration_ids: list[tuple[Gio.DBusInterfaceInfo, int]] = []
        self._cover_path = _cover_temp_path()
        self._cover_uri = ""
        self._cached_meta: dict = {}
        self._last_position_ms = 0

        self._position_timer = QTimer(self)
        self._position_timer.setInterval(1000)
        self._position_timer.setSingleShot(True)
        self._position_timer.timeout.connect(self._emit_position)

        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            MPRIS2_BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            self._on_name_lost,
        )

    # ------------------------------------------------------------------
    #  D-Bus lifecycle
    # ------------------------------------------------------------------

    def _on_bus_acquired(self, connection, name):
        self._connection = connection
        for info, iface in [
            (_IFACE_ROOT, None),
            (_IFACE_PLAYER, None),
            (_IFACE_PROPERTIES, None),
        ]:
            reg_id = connection.register_object(
                MPRIS2_OBJECT_PATH,
                info,
                self._handle_method_call,
                self._handle_get_property,
                self._handle_set_property,
            )
            if reg_id:
                self._registration_ids.append((info, reg_id))

    def _on_name_lost(self, connection, name):
        import sys
        print(f"[mpris2] lost bus name: {name}", file=sys.stderr)

    # ------------------------------------------------------------------
    #  D-Bus method dispatch
    # ------------------------------------------------------------------

    def _handle_method_call(self, connection, sender, object_path,
                            interface_name, method_name, parameters,
                            invocation):
        if interface_name == "org.mpris.MediaPlayer2":
            if method_name == "Raise":
                self.raiseRequested.emit()
                invocation.return_value(None)
            elif method_name == "Quit":
                self.quitRequested.emit()
                invocation.return_value(None)
            else:
                invocation.return_value(None)

        elif interface_name == "org.mpris.MediaPlayer2.Player":
            if method_name == "Play":
                self._controller.play()
            elif method_name == "Pause":
                self._controller.pause()
            elif method_name == "PlayPause":
                self._controller.toggle()
            elif method_name == "Stop":
                self._controller.stop()
            elif method_name == "Next":
                self._controller.next_track()
            elif method_name == "Previous":
                self._controller.prev_track()
            elif method_name == "Seek":
                offset_us = parameters.unpack()[0]
                new_pos = self._engine.position + offset_us // 1000
                self._engine.seek(max(0, new_pos))
                self._emit_position_immediate()
            elif method_name == "SetPosition":
                _, pos_us = parameters.unpack()
                self._engine.seek(max(0, pos_us // 1000))
                self._emit_position_immediate()
            invocation.return_value(None)

        elif interface_name == "org.freedesktop.DBus.Properties":
            self._handle_properties_method(method_name, parameters, invocation)

    def _handle_get_property(self, connection, sender, object_path,
                             interface_name, property_name):
        return self._get_property_value(interface_name, property_name)

    def _handle_set_property(self, connection, sender, object_path,
                             interface_name, property_name, value):
        if interface_name == "org.mpris.MediaPlayer2.Player" and property_name == "Volume":
            self._engine.volume = max(0.0, min(value.get_double(), 1.5))

    def _handle_properties_method(self, method_name, parameters, invocation):
        if method_name == "Get":
            iface, prop = parameters.unpack()
            value = self._get_property_value(iface, prop)
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method_name == "Set":
            iface, prop, value = parameters.unpack()
            if iface == "org.mpris.MediaPlayer2.Player" and prop == "Volume":
                self._engine.volume = max(0.0, min(value.get_double(), 1.5))
            invocation.return_value(None)
        elif method_name == "GetAll":
            iface = parameters.unpack()[0]
            props = self._get_all_properties(iface)
            invocation.return_value(GLib.Variant("(a{sv})", (props,)))

    # ------------------------------------------------------------------
    #  D-Bus property getters
    # ------------------------------------------------------------------

    def _get_property_value(self, iface, prop):
        if iface == "org.mpris.MediaPlayer2":
            return self._get_root_property(prop)
        elif iface == "org.mpris.MediaPlayer2.Player":
            return self._get_player_property(prop)
        return GLib.Variant("s", "")

    def _get_root_property(self, prop):
        if prop == "CanQuit":
            return GLib.Variant("b", True)
        if prop == "CanRaise":
            return GLib.Variant("b", True)
        if prop == "HasTrackList":
            return GLib.Variant("b", False)
        if prop == "Identity":
            return GLib.Variant("s", "VB Player")
        if prop == "DesktopEntry":
            return GLib.Variant("s", "vb-player")
        if prop == "SupportedMimeTypes":
            return GLib.Variant("as", _SUPPORTED_MIMES)
        if prop == "SupportedUriSchemes":
            return GLib.Variant("as", ["file"])
        return GLib.Variant("b", False)

    def _get_player_property(self, prop):
        if prop == "PlaybackStatus":
            return GLib.Variant("s", _STATUS_MAP.get(self._engine.state, "Stopped"))
        if prop == "Metadata":
            return self._build_metadata_variant()
        if prop == "Volume":
            return GLib.Variant("d", max(0.0, self._engine.volume))
        if prop == "Position":
            return GLib.Variant("x", self._engine.position * 1000)
        if prop == "MinimumRate":
            return GLib.Variant("d", 1.0)
        if prop == "MaximumRate":
            return GLib.Variant("d", 1.0)
        if prop == "CanGoNext":
            return GLib.Variant("b", self._playlist.count > 1)
        if prop == "CanGoPrevious":
            return GLib.Variant("b", self._playlist.count > 1)
        if prop in ("CanPlay", "CanPause", "CanControl"):
            return GLib.Variant("b", True)
        if prop == "CanSeek":
            return GLib.Variant("b", self._engine.duration > 0)
        return GLib.Variant("b", False)

    def _get_all_properties(self, iface):
        if iface == "org.mpris.MediaPlayer2":
            names = ["CanQuit", "CanRaise", "HasTrackList", "Identity",
                     "DesktopEntry", "SupportedMimeTypes", "SupportedUriSchemes"]
        elif iface == "org.mpris.MediaPlayer2.Player":
            names = ["PlaybackStatus", "Metadata", "Volume", "Position",
                     "MinimumRate", "MaximumRate", "CanGoNext", "CanGoPrevious",
                     "CanPlay", "CanPause", "CanSeek", "CanControl"]
        else:
            return {}
        return {n: self._get_property_value(iface, n) for n in names}

    def _build_metadata_variant(self):
        d = {}
        filepath = self._engine.current_file
        if filepath:
            track_id = f"/org/vbplayer/track/{abs(hash(filepath)) % (10**8)}"
            d["mpris:trackid"] = GLib.Variant("o", track_id)
        d["mpris:length"] = GLib.Variant("x", self._engine.duration * 1000)
        if self._cached_meta:
            m = self._cached_meta
            if m.get("title"):
                d["xesam:title"] = GLib.Variant("s", m["title"])
            if m.get("artist"):
                d["xesam:artist"] = GLib.Variant("as", [m["artist"]])
            if m.get("album"):
                d["xesam:album"] = GLib.Variant("s", m["album"])
            if m.get("album_artist"):
                d["xesam:albumArtist"] = GLib.Variant("as", [m["album_artist"]])
            if m.get("track_number"):
                d["xesam:trackNumber"] = GLib.Variant("i", m["track_number"])
        if self._cover_uri:
            d["mpris:artUrl"] = GLib.Variant("s", self._cover_uri)
        return GLib.Variant("a{sv}", d)

    # ------------------------------------------------------------------
    #  PropertiesChanged emission
    # ------------------------------------------------------------------

    def _emit_properties_changed(self, iface_name, changed_props):
        if not self._connection:
            return
        variant = GLib.Variant("(sa{sv}as)", (iface_name, changed_props, []))
        self._connection.emit_signal(
            None,
            MPRIS2_OBJECT_PATH,
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            variant,
        )

    def _emit_player_prop(self, prop_name, value):
        self._emit_properties_changed(
            "org.mpris.MediaPlayer2.Player",
            {prop_name: value},
        )

    # ------------------------------------------------------------------
    #  Signal wiring (call from MainWindow after construction)
    # ------------------------------------------------------------------

    def connect_signals(self):
        self._engine.stateChanged.connect(self._on_state_changed)
        self._engine.positionChanged.connect(self._on_position_changed)
        self._engine.durationChanged.connect(self._on_duration_changed)
        self._engine.volumeChanged.connect(self._on_volume_changed)
        self._controller.metadataLoaded.connect(self._on_metadata_loaded)

    def _on_state_changed(self, state):
        status = _STATUS_MAP.get(state, "Stopped")
        self._emit_player_prop("PlaybackStatus", GLib.Variant("s", status))
        if state != PlaybackState.Playing:
            self._position_timer.stop()
            self._emit_position()

    def _on_position_changed(self, ms):
        self._last_position_ms = ms
        if not self._position_timer.isActive():
            self._position_timer.start()

    def _emit_position(self):
        self._emit_player_prop(
            "Position", GLib.Variant("x", self._last_position_ms * 1000)
        )

    def _emit_position_immediate(self):
        self._position_timer.stop()
        self._emit_position()

    def _on_duration_changed(self, ms):
        self._emit_player_prop(
            "Metadata", self._build_metadata_variant()
        )

    def _on_volume_changed(self, vol):
        self._emit_player_prop("Volume", GLib.Variant("d", max(0.0, vol)))

    def _on_metadata_loaded(self, meta, filepath):
        self._cached_meta = {
            "title": getattr(meta, "title", "") or "",
            "artist": getattr(meta, "artist", "") or "",
            "album": getattr(meta, "album", "") or "",
            "album_artist": getattr(meta, "album_artist", "") or "",
            "track_number": getattr(meta, "track_number", None),
        }
        self._update_cover_art(getattr(meta, "cover_data", None))
        self._emit_player_prop("Metadata", self._build_metadata_variant())

    def _update_cover_art(self, cover_data):
        if cover_data:
            try:
                from io import BytesIO
                from PyQt6.QtCore import QSettings
                from PIL import Image, ImageDraw
                img = Image.open(BytesIO(cover_data)).convert("RGBA")
                size = min(img.width, img.height, 256)
                img = img.resize((size, size), Image.LANCZOS)
                # Use app UI radius
                r = int(QSettings("VBPlayer", "VB Player").value("ui_radius", 12) or 12)
                mask = Image.new("L", (size, size), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle([0, 0, size, size], radius=r, fill=255)
                rounded = Image.new("RGBA", (size, size))
                rounded.paste(img, mask=mask)
                buf = BytesIO()
                rounded.save(buf, "PNG")
                import hashlib
                h = hashlib.md5(cover_data).hexdigest()[:8]
                cover_dir = _cover_temp_path().parent
                for old in list(cover_dir.glob("vbplayer_cover_*")):
                    try: old.unlink()
                    except OSError: pass
                self._cover_path = cover_dir / f"vbplayer_cover_{h}.png"
                self._cover_path.write_bytes(buf.getvalue())
                self._cover_uri = self._cover_path.as_uri()
            except Exception:
                self._cover_uri = ""
        else:
            self._cover_uri = ""

    # ------------------------------------------------------------------
    #  Cleanup
    # ------------------------------------------------------------------

    def cleanup(self):
        self._position_timer.stop()
        if self._connection:
            for _, reg_id in self._registration_ids:
                self._connection.unregister_object(reg_id)
            self._registration_ids.clear()
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        try:
            if self._cover_path.is_file():
                self._cover_path.unlink()
        except OSError:
            pass
