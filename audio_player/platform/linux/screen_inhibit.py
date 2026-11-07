"""Prevent screen dimming/sleeping while the immersive page is visible.

Uses the desktop's idle-inhibit APIs via D-Bus:
  * GNOME: org.gnome.SessionManager.Inhibit (flag 8 = inhibit idle)
  * fallback: org.freedesktop.ScreenSaver.Inhibit
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

APP_ID = "vbplayer"
_INHIBIT_IDLE = 8  # org.gnome.SessionManager inhibit flag


class ScreenInhibitor:
    def __init__(self):
        self._connection = None
        self._cookie: int | None = None
        self._mode = ""

    def inhibit(self, reason: str = "Immersive playback") -> None:
        if self._cookie is not None:
            return
        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            return

        # GNOME / capable session managers.
        try:
            result = connection.call_sync(
                "org.gnome.SessionManager",
                "/org/gnome/SessionManager",
                "org.gnome.SessionManager",
                "Inhibit",
                GLib.Variant("(susu)", (APP_ID, 0, reason, _INHIBIT_IDLE)),
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            self._cookie = int(result.unpack()[0])
            self._connection = connection
            self._mode = "gnome"
            return
        except Exception:
            pass

        # KDE / generic freedesktop screensaver.
        try:
            result = connection.call_sync(
                "org.freedesktop.ScreenSaver",
                "/org/freedesktop/ScreenSaver",
                "org.freedesktop.ScreenSaver",
                "Inhibit",
                GLib.Variant("(ss)", (APP_ID, reason)),
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            self._cookie = int(result.unpack()[0])
            self._connection = connection
            self._mode = "freedesktop"
        except Exception:
            pass

    def uninhibit(self) -> None:
        if self._cookie is None or self._connection is None:
            return
        try:
            if self._mode == "gnome":
                self._connection.call_sync(
                    "org.gnome.SessionManager",
                    "/org/gnome/SessionManager",
                    "org.gnome.SessionManager",
                    "Uninhibit",
                    GLib.Variant("(u)", (self._cookie,)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
            else:
                self._connection.call_sync(
                    "org.freedesktop.ScreenSaver",
                    "/org/freedesktop/ScreenSaver",
                    "org.freedesktop.ScreenSaver",
                    "Uninhibit",
                    GLib.Variant("(u)", (self._cookie,)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
        except Exception:
            pass
        finally:
            self._cookie = None
            self._connection = None
            self._mode = ""
